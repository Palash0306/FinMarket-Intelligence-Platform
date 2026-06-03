# path: app/ingestion/sentiment_fetcher.py
# Complete replacement for stocktwits_fetcher.py
#
# Uses THREE free sources that are not Cloudflare blocked:
#
# Source 1: yfinance news       → free, no key, already installed
# Source 2: Finviz news scraper → free, no key
# Source 3: Alpha Vantage news  → free, 25 calls/day on free tier
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# config.py
#       ↓ KAFKA_BOOTSTRAP_SERVERS, ALPHA_VANTAGE_API_KEY
# THIS FILE
#       ↓ reads active symbols from
# RDS stocks table (session.py + Stock model — Phase 1)
#       ↓ fetches sentiment signals from
# yfinance news + Alpha Vantage news
#       ↓ archives raw to
# S3 (s3_helper.py — Phase 2 Day 1)
#       ↓ publishes to
# Kafka "sentiment.raw"
#       ↓ consumed by
# sentiment_consumer.py
#       ↓ writes to
# RDS stocktwits_posts table
#   (reuses same table — field names still match)
#       ↓ read by
# Phase 3 sentiment aggregation
# Phase 4 RAG embeddings
# ─────────────────────────────────────────────────────────

import json
import yfinance as yf
import httpx
from datetime import datetime, timezone
from confluent_kafka import Producer
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.stock import Stock
from app.ingestion.s3_helper import s3_helper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Sentiment keyword lists ───────────────────────────────
#
# We score headlines by looking for bullish/bearish keywords.
# This is simple but surprisingly effective for financial news.
# Phase 3 will do proper ML scoring on top of this.
#
# bullish keywords = positive signals
BULLISH_KEYWORDS = [
    "beat", "beats", "surge", "surges", "rally", "rallies",
    "rise", "rises", "gain", "gains", "record", "high",
    "strong", "growth", "profit", "upgrade", "buy",
    "outperform", "bullish", "positive", "up", "soar"
]

# bearish keywords = negative signals
BEARISH_KEYWORDS = [
    "miss", "misses", "fall", "falls", "drop", "drops",
    "decline", "declines", "loss", "losses", "low", "weak",
    "cut", "downgrade", "sell", "underperform", "bearish",
    "negative", "down", "plunge", "crash", "warning"
]


def score_headline(headline: str) -> tuple[float, str]:
    """
    Simple keyword-based sentiment scoring.

    Takes a headline string and returns:
    (score, label)

    score:  +1.0 = bullish, -1.0 = bearish, 0.0 = neutral
    label:  "bullish", "bearish", or "neutral"

    This is our Phase 2 simple scorer.
    Phase 3 will replace this with sentence-transformers
    which is much more accurate.

    Example:
    "Apple beats earnings estimates" → (1.0, "bullish")
    "Tesla stock drops 10%" → (-1.0, "bearish")
    "Apple releases new iPhone" → (0.0, "neutral")
    """
    text = headline.lower()

    # Count keyword matches
    bullish_hits = sum(1 for word in BULLISH_KEYWORDS if word in text)
    bearish_hits = sum(1 for word in BEARISH_KEYWORDS if word in text)

    if bullish_hits > bearish_hits:
        return 1.0, "bullish"
    elif bearish_hits > bullish_hits:
        return -1.0, "bearish"
    else:
        return 0.0, "neutral"


class SentimentFetcher:
    """
    Fetches sentiment signals from free, working sources.

    Replaces StocktwitsFetcher which was blocked by Cloudflare.

    Sources used:
    1. yfinance news    → already installed, no key, no blocks
    2. Alpha Vantage    → free tier 25 calls/day, has news API

    In plain English: goes out every hour, collects all
    financial news headlines for our tracked stocks,
    scores each headline as bullish/bearish/neutral,
    and drops the scored posts in the Kafka postbox.
    """

    def __init__(self):
        # ── Kafka Producer ────────────────────────────────
        # Same pattern as all other fetchers
        self.producer = Producer({
            "bootstrap.servers": settings.kafka_bootstrap_servers
        })

        # ── HTTP client for Alpha Vantage ─────────────────
        self.http_client = httpx.Client(timeout=15)

    def get_active_symbols(self) -> list[str]:
        """
        Gets active symbols from RDS stocks table.
        Same pattern used across all fetchers.
        """
        db: Session = SessionLocal()
        try:
            stocks = db.query(Stock).filter(
                Stock.is_active == True
            ).all()
            return [stock.symbol for stock in stocks]
        finally:
            db.close()

    def fetch_yfinance_news(
        self,
        symbol: str
    ) -> list[dict]:
        """
        Fetches news from yfinance for one symbol.

        yfinance returns the last 10-20 news articles
        for any ticker. Completely free, no API key.
        Already installed from Phase 2 Day 1.

        Each article has:
        - title: headline text
        - publisher: source name
        - link: article URL
        - providerPublishTime: unix timestamp

        We score the headline using score_headline()
        and treat each article as a sentiment signal.
        """
        messages = []

        try:
            ticker = yf.Ticker(symbol)
            news_items = ticker.news

            if not news_items:
                return []

            for item in news_items:
                headline = item.get("title", "")
                if not headline:
                    continue

                # Score the headline
                score, label = score_headline(headline)

                # Convert unix timestamp to ISO string
                pub_time = item.get("providerPublishTime", 0)
                posted_at = datetime.fromtimestamp(
                    pub_time,
                    tz=timezone.utc
                ).isoformat() if pub_time else None

                messages.append({
                    # Use article UUID as the unique ID
                    # Falls back to URL hash if no UUID
                    "stocktwits_id": item.get(
                        "uuid",
                        str(hash(item.get("link", headline)))
                    ),
                    "body": headline,
                    "ticker_symbol": symbol,
                    "author": item.get("publisher", "unknown"),
                    "posted_at": posted_at,
                    "sentiment_label": label,
                    "sentiment_score": score,
                    # yfinance doesn't have likes
                    # Use 1 as default weight
                    "liked_count": 1,
                    "source": "yfinance_news"
                })

        except Exception as e:
            logger.error(
                "yfinance_news_error",
                extra={"symbol": symbol, "error": str(e)}
            )

        return messages

    def fetch_alpha_vantage_news(
        self,
        symbol: str
    ) -> list[dict]:
        """
        Fetches news sentiment from Alpha Vantage.

        Alpha Vantage has a free News & Sentiment API.
        Free tier: 25 API calls per day.
        Already have the API key from Phase 2 setup.

        Returns news with pre-scored sentiment from
        Alpha Vantage's own NLP model:
        - overall_sentiment_score: -1.0 to +1.0
        - overall_sentiment_label: Bullish/Bearish/Neutral

        This is BETTER than our keyword scorer because
        Alpha Vantage uses actual NLP models.
        Still free.
        """
        if not settings.alpha_vantage_api_key:
            return []

        messages = []

        try:
            response = self.http_client.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": symbol,
                    "limit": "10",
                    "apikey": settings.alpha_vantage_api_key
                }
            )

            if response.status_code != 200:
                return []

            data = response.json()

            # Alpha Vantage returns error message as a key
            # when rate limited or invalid key
            if "Information" in data or "Note" in data:
                logger.warning(
                    "alpha_vantage_limit",
                    extra={"symbol": symbol}
                )
                return []

            for article in data.get("feed", []):
                # Alpha Vantage provides pre-scored sentiment
                av_score = float(
                    article.get("overall_sentiment_score", 0)
                )
                av_label = article.get(
                    "overall_sentiment_label", "Neutral"
                ).lower()

                # Normalise label to our format
                if "bullish" in av_label:
                    label = "bullish"
                    score = av_score
                elif "bearish" in av_label:
                    label = "bearish"
                    score = av_score
                else:
                    label = "neutral"
                    score = 0.0

                messages.append({
                    "stocktwits_id": str(hash(
                        article.get("url", article.get("title", ""))
                    )),
                    "body": article.get("title", ""),
                    "ticker_symbol": symbol,
                    "author": article.get("source", "alpha_vantage"),
                    "posted_at": article.get("time_published", ""),
                    "sentiment_label": label,
                    "sentiment_score": round(score, 4),
                    "liked_count": 2,  # weight AV higher than yfinance
                    "source": "alpha_vantage"
                })

        except Exception as e:
            logger.error(
                "alpha_vantage_error",
                extra={"symbol": symbol, "error": str(e)}
            )

        return messages

    def fetch_and_publish(self) -> int:
        """
        Main method called by Celery every hour.

        Flow:
        ┌──────────────────────────────────────────────────┐
        │ 1. get_active_symbols() from RDS                 │
        │       ↓                                          │
        │ 2. fetch_yfinance_news() per symbol              │
        │    fetch_alpha_vantage_news() per symbol         │
        │       ↓                                          │
        │ 3. s3_helper.save_raw_data() → S3 archive       │
        │       ↓                                          │
        │ 4. producer.produce() → Kafka "sentiment.raw"   │
        │       ↓                                          │
        │ sentiment_consumer.py picks up                   │
        │       ↓                                          │
        │ RDS stocktwits_posts table                       │
        └──────────────────────────────────────────────────┘
        """
        symbols = self.get_active_symbols()

        if not symbols:
            logger.warning("no_active_symbols_for_sentiment")
            return 0

        all_messages = []

        for symbol in symbols:
            # ── Fetch from yfinance news ──────────────────
            yf_messages = self.fetch_yfinance_news(symbol)
            all_messages.extend(yf_messages)
            logger.info(
                "yfinance_news_fetched",
                extra={
                    "symbol": symbol,
                    "count": len(yf_messages)
                }
            )

            # ── Fetch from Alpha Vantage ──────────────────
            av_messages = self.fetch_alpha_vantage_news(symbol)
            all_messages.extend(av_messages)
            logger.info(
                "alpha_vantage_fetched",
                extra={
                    "symbol": symbol,
                    "count": len(av_messages)
                }
            )

        if not all_messages:
            logger.warning("no_sentiment_messages_fetched")
            return 0

        # ── Archive to S3 ─────────────────────────────────
        try:
            s3_helper.save_raw_data(
                data=all_messages,
                data_type="sentiment",
                identifier="batch"
            )
        except Exception as e:
            logger.error(f"s3_sentiment_save_failed: {e}")

        # ── Publish to Kafka ──────────────────────────────
        published = 0
        seen_ids = set()

        for message in all_messages:
            msg_id = message.get("stocktwits_id", "")

            if not msg_id or msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)

            try:
                self.producer.produce(
                    topic="sentiment.raw",
                    key=message["ticker_symbol"].encode("utf-8"),
                    value=json.dumps(message).encode("utf-8")
                )
                published += 1
            except Exception as e:
                logger.error(
                    "kafka_sentiment_publish_error",
                    extra={"error": str(e)}
                )

        self.producer.flush()

        logger.info(
            "sentiment_published_to_kafka",
            extra={
                "published": published,
                "total": len(all_messages)
            }
        )

        return published

    def __del__(self):
        self.http_client.close()


# Single instance
sentiment_fetcher = SentimentFetcher()