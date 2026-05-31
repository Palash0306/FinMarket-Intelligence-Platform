# path: app/ingestion/news_fetcher.py

# =========================================================
# NEWS FETCHER
# =========================================================
#
# What does this file do in plain English?
#
# Every 30 minutes, Celery wakes this up.
# It goes to two places to collect financial news:
# 1. NewsAPI  — searches 80,000+ news sources by ticker
# 2. RSS feeds — direct headline feeds from Reuters,
#                Yahoo Finance, MarketWatch
#
# Then it:
# - Saves the raw articles to S3 (permanent archive)
# - Publishes each article to Kafka "news.raw"
# - news_consumer.py picks them up and saves to RDS
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO EVERYTHING ELSE:
#
# .env ──────────────────────────────────────────────────┐
#       ↓ NEWS_API_KEY read by config.py                 │
# config.py                                              │
#       ↓ settings.news_api_key                          │
# THIS FILE (news_fetcher.py)                            │
#       ↓ reads active symbols from                      │
# RDS stocks table ─────────────────── (Phase 1)        │
# session.py + Stock model                               │
#       ↓ fetches articles from                          │
# NewsAPI (100 req/day free) ←─────────────────────────┘
# RSS feeds (unlimited, free)
#       ↓ saves raw batch to
# S3 news/date/batch.json ─────────── (s3_helper Day 1)
#       ↓ publishes each article to
# Kafka "news.raw" topic ──────────── (Kafka Day 1)
#       ↓ consumed by
# news_consumer.py ────────────────── (built below)
#       ↓ writes to
# RDS news_articles table ─────────── (NewsArticle model above)
#       ↓ read by
# Phase 3 NLP sentiment model
# Phase 4 RAG embedding layer
# ─────────────────────────────────────────────────────────

import json
import feedparser
from datetime import datetime, timezone
from newsapi import NewsApiClient
from confluent_kafka import Producer
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.stock import Stock
from app.ingestion.s3_helper import s3_helper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Free RSS feeds — zero setup needed ───────────────────
#
# RSS = Really Simple Syndication
# A standard format news sites use to publish articles.
# feedparser reads RSS feeds automatically.
# No API key, no registration, completely free.
#
# Reuters:     global business and finance news
# Yahoo Finance: stock-specific news aggregator
# MarketWatch:  US markets focused news
RSS_FEEDS = {
    "rss_reuters":    "https://feeds.reuters.com/reuters/businessNews",
    "rss_yahoo":      "https://finance.yahoo.com/news/rssindex",
    "rss_marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories",
}


class NewsFetcher:
    """
    Fetches financial news from NewsAPI and RSS feeds.

    In plain English: the newspaper delivery service.
    Goes out every 30 minutes, collects all financial
    news relevant to our tracked stocks, and drops
    it in the Kafka postbox for the consumer to file.

    Connects to:
    ┌─────────────────────────────────────────────┐
    │ config.py      → API key                    │
    │ session.py     → DB connection              │
    │ Stock model    → which symbols to search    │
    │ s3_helper.py   → archive raw data           │
    │ Kafka Producer → publish to news.raw topic  │
    └─────────────────────────────────────────────┘
    """

    def __init__(self):

        # ── NewsAPI client ────────────────────────────────
        #
        # NewsApiClient wraps all NewsAPI HTTP calls.
        # Gets the key from config.py → .env
        # Free tier: 100 requests per day
        # Each request = up to 100 articles
        if settings.news_api_key:
            self.newsapi = NewsApiClient(
                api_key=settings.news_api_key
            )
            logger.info("newsapi_client_ready")
        else:
            self.newsapi = None
            logger.warning(
                "NEWS_API_KEY missing — "
                "only RSS feeds will be used"
            )

        # ── Kafka Producer ────────────────────────────────
        #
        # Same pattern as stock_fetcher.py (Day 1).
        # Sends messages to Kafka "news.raw" topic.
        # bootstrap.servers → where Kafka is running
        # → "kafka:9092" inside Docker (service name)
        self.producer = Producer({
            "bootstrap.servers": settings.kafka_bootstrap_servers
        })

    def get_active_symbols(self) -> list[tuple[str, str]]:
        """
        Gets active stocks from RDS.

        Connects to:
        session.py → opens DB connection
        Stock model → queries stocks table
        Returns [(symbol, company_name), ...]
        e.g. [("AAPL", "Apple Inc."), ("MSFT", ...)]

        We return both symbol AND company name because
        searching "AAPL" misses articles that say
        "Apple reported earnings" without the ticker.
        """
        db: Session = SessionLocal()
        try:
            stocks = db.query(Stock).filter(
                Stock.is_active == True
            ).all()
            return [
                (stock.symbol, stock.company_name)
                for stock in stocks
            ]
        finally:
            # Always close the session (from session.py pattern)
            db.close()

    def fetch_from_newsapi(
        self,
        symbol: str,
        company_name: str
    ) -> list[dict]:
        """
        Fetches articles from NewsAPI for one stock.

        Searches by ticker symbol e.g. "AAPL stock".
        Returns max 20 articles per call.

        Why "AAPL stock" not just "AAPL"?
        Searching "AAPL" alone returns too much noise.
        Adding "stock" filters for financial articles.

        Connects to:
        NewsAPI HTTP endpoint → returns article list
        """
        if not self.newsapi:
            return []

        articles = []

        try:
            # ── Search NewsAPI ────────────────────────────
            #
            # get_everything() searches ALL articles
            # across all 80,000+ sources NewsAPI aggregates.
            #
            # q = search query (like a Google search)
            # language = "en" = English articles only
            # sort_by = "publishedAt" = newest first
            # page_size = 20 = max 20 per API call
            response = self.newsapi.get_everything(
                q=f"{symbol} stock",
                language="en",
                sort_by="publishedAt",
                page_size=20
            )

            for article in response.get("articles", []):

                # ── Normalise to our format ───────────────
                #
                # Different news sources use different field
                # names in their API. We normalise everything
                # to our own consistent format here.
                # This is called "ETL" — Extract, Transform, Load.
                # Extract: get from NewsAPI
                # Transform: normalise field names
                # Load: publish to Kafka (consumer loads to RDS)
                articles.append({
                    "url":            article.get("url", ""),
                    "headline":       article.get("title", ""),

                    # content = full text if available
                    # description = summary if no full text
                    "body":           (
                                        article.get("content") or
                                        article.get("description", "")
                                      ),
                    "source":         "newsapi",
                    "author":         article.get("author", ""),
                    "published_at":   article.get("publishedAt", ""),

                    # ticker_symbols set to the symbol we searched for
                    # Phase 3 spaCy NER will enrich this further
                    "ticker_symbols": symbol,
                    "fetched_at":     datetime.now(timezone.utc).isoformat()
                })

        except Exception as e:
            logger.error(
                "newsapi_fetch_error",
                extra={"symbol": symbol, "error": str(e)}
            )

        return articles

    def fetch_from_rss(self) -> list[dict]:
        """
        Fetches articles from all RSS feeds.

        RSS feeds return general financial headlines —
        they don't filter by ticker symbol.
        We store all of them and let Phase 3 spaCy NER
        figure out which tickers each article mentions.

        feedparser.parse() handles:
        - Making the HTTP request to the RSS URL
        - Parsing the XML response
        - Returning structured entry objects

        Connects to:
        RSS_FEEDS dict → list of URLs to parse
        feedparser     → parses each feed
        """
        articles = []

        for feed_name, feed_url in RSS_FEEDS.items():
            try:
                # ── Parse RSS feed ────────────────────────
                #
                # feedparser downloads and parses the RSS XML.
                # feed.entries = list of article objects.
                # We take max 20 per feed to stay manageable.
                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:20]:
                    articles.append({
                        "url":            entry.get("link", ""),
                        "headline":       entry.get("title", ""),
                        "body":           entry.get("summary", ""),
                        "source":         feed_name,
                        "author":         entry.get("author", ""),
                        "published_at":   entry.get("published", ""),

                        # ticker_symbols = None for RSS articles
                        # Phase 3 spaCy NER fills this in
                        "ticker_symbols": None,
                        "fetched_at":     datetime.now(
                                              timezone.utc
                                          ).isoformat()
                    })

            except Exception as e:
                logger.error(
                    "rss_fetch_error",
                    extra={"feed": feed_name, "error": str(e)}
                )

        return articles

    def fetch_and_publish(self) -> int:
        """
        Main method — called by Celery every 30 minutes.

        Complete flow:
        ┌─────────────────────────────────────────────────┐
        │ 1. get_active_symbols()                         │
        │    → reads RDS stocks table (Phase 1)           │
        │    → returns ["AAPL", "MSFT", ...]              │
        │                                                  │
        │ 2. fetch_from_newsapi() per symbol              │
        │    → calls NewsAPI HTTP endpoint                 │
        │    → returns article list                        │
        │                                                  │
        │ 3. fetch_from_rss()                             │
        │    → calls all RSS feed URLs                    │
        │    → returns headline list                       │
        │                                                  │
        │ 4. s3_helper.save_raw_data()                    │
        │    → archives everything to S3                   │
        │    → path: news/2024-01-15/batch_093000.json    │
        │                                                  │
        │ 5. producer.produce() per article               │
        │    → publishes to Kafka "news.raw"              │
        │    → news_consumer.py picks up and saves to RDS │
        └─────────────────────────────────────────────────┘

        Returns: count of articles published to Kafka
        """
        stocks = self.get_active_symbols()
        all_articles = []

        # ── Fetch from NewsAPI ────────────────────────────
        for symbol, company_name in stocks:
            articles = self.fetch_from_newsapi(
                symbol, company_name
            )
            all_articles.extend(articles)
            logger.info(
                "newsapi_fetched",
                extra={"symbol": symbol, "count": len(articles)}
            )

        # ── Fetch from RSS feeds ──────────────────────────
        rss_articles = self.fetch_from_rss()
        all_articles.extend(rss_articles)
        logger.info(
            "rss_fetched",
            extra={"count": len(rss_articles)}
        )

        if not all_articles:
            logger.warning("no_articles_fetched")
            return 0

        # ── Archive raw batch to S3 ───────────────────────
        #
        # s3_helper from Day 1 — reused here unchanged.
        # Archives the entire batch as one JSON file.
        # If we need to reprocess, S3 has the original data.
        try:
            s3_helper.save_raw_data(
                data=all_articles,
                data_type="news",
                identifier="batch"
            )
        except Exception as e:
            # S3 failure NEVER stops Kafka publishing
            # Log it, but keep going
            logger.error(f"s3_save_failed_continuing: {e}")

        # ── Publish to Kafka ──────────────────────────────
        #
        # One message per article.
        # We deduplicate URLs within this batch first.
        # news_consumer.py also deduplicates by URL in RDS.
        # Double deduplication = no duplicate articles ever.
        published = 0
        seen_urls = set()

        for article in all_articles:
            url = article.get("url", "")

            # Skip blank URLs or URLs we already published
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            try:
                self.producer.produce(
                    # "news.raw" = Kafka topic name
                    # Think of it as the "mailbox address"
                    topic="news.raw",

                    # key = source name
                    # Groups same-source articles in Kafka
                    key=article.get(
                        "source", "unknown"
                    ).encode("utf-8"),

                    # value = article data as JSON bytes
                    value=json.dumps(article).encode("utf-8")
                )
                published += 1

            except Exception as e:
                logger.error(
                    "kafka_news_publish_error",
                    extra={"error": str(e)}
                )

        # flush() = actually send all queued messages
        # Like pressing "send all" on a batch of emails
        self.producer.flush()

        logger.info(
            "news_published_to_kafka",
            extra={
                "published": published,
                "total": len(all_articles)
            }
        )

        return published


# Single instance — Celery tasks import and reuse this
news_fetcher = NewsFetcher()