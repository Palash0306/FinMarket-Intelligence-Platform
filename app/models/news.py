# path: app/models/news.py

# =========================================================
# NEWS ARTICLE MODEL
# =========================================================
#
# What is this file in plain English?
#
# This defines the news_articles TABLE in your RDS database.
# Every news article we fetch from NewsAPI or RSS feeds
# gets stored as one row in this table.
#
# Think of it like designing a spreadsheet:
# - Each column = one field (headline, url, body...)
# - Each row    = one news article
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO EVERYTHING ELSE:
#
# NewsAPI / RSS feeds
#       ↓ raw articles fetched by
# news_fetcher.py
#       ↓ publishes article data to
# Kafka "news.raw" topic
#       ↓ consumed by
# news_consumer.py
#       ↓ uses THIS MODEL to insert rows into
# RDS news_articles table
#       ↓ read by
# Phase 3 ── sentiment model fills sentiment_score column
# Phase 4 ── RAG layer embeds body text into pgvector
#             sets is_embedded = True when done
#
# WHY RDS (POSTGRES) NOT CLICKHOUSE?
#
# ClickHouse  = best for NUMBERS over time (prices)
# Postgres    = best for TEXT, relationships, vector search
# News articles are TEXT → Postgres is the right choice
# pgvector in Phase 4 needs Postgres, not ClickHouse
# ─────────────────────────────────────────────────────────

from sqlalchemy import Column, Integer, String, Text, Float, Index
from sqlalchemy.orm import Mapped, mapped_column

# Base       = parent class all models inherit from (Phase 1)
# TimestampMixin = adds created_at + updated_at automatically
from app.models.base import Base, TimestampMixin


class NewsArticle(Base, TimestampMixin):
    """
    Represents one news article in the database.

    Sources:
    - NewsAPI (aggregates 80,000+ news sources)
    - RSS feeds (Reuters, Yahoo Finance, MarketWatch)

    Lifecycle of one article:
    1. Fetched by news_fetcher.py  → raw
    2. Saved to S3                 → archived forever
    3. Published to Kafka          → queued for processing
    4. Saved here by consumer      → stored in RDS
    5. Phase 3 fills sentiment     → analysed
    6. Phase 4 creates embedding   → searchable by AI
    """

    # ── Table name in RDS ─────────────────────────────────
    # What you'll see in Adminer at localhost:8080
    __tablename__ = "news_articles"

    # ── Primary key ───────────────────────────────────────
    #
    # Auto-increments: 1, 2, 3...
    # Every table needs a unique identifier for each row
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="Auto-incrementing unique row ID"
    )

    # ── URL ───────────────────────────────────────────────
    #
    # url is our DEDUPLICATION KEY.
    # If we fetch the same article twice (NewsAPI and RSS
    # might both return a Reuters article), we use the URL
    # to detect it's a duplicate and skip it.
    #
    # unique=True = RDS enforces: no two rows with same URL
    # index=True  = fast lookups when checking duplicates
    url: Mapped[str] = mapped_column(
        String(2048),
        unique=True,
        nullable=False,
        index=True,
        comment="Article URL — primary deduplication key"
    )

    # ── Headline ──────────────────────────────────────────
    #
    # The article title shown in the dashboard (Phase 5)
    # String(1024) = max 1024 characters
    headline: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="Article headline / title"
    )

    # ── Body ──────────────────────────────────────────────
    #
    # Full article text.
    # Text = unlimited length (no character limit)
    # Used by:
    # - Phase 3 spaCy NER (extracts ticker mentions)
    # - Phase 3 sentiment model (scores the text)
    # - Phase 4 RAG (embeds into pgvector for AI search)
    body: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Full article text — used by Phase 3 NLP and Phase 4 RAG"
    )

    # ── Source ────────────────────────────────────────────
    #
    # Where the article came from.
    # Values: "newsapi", "rss_reuters", "rss_yahoo",
    #         "rss_marketwatch"
    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Source: newsapi / rss_reuters / rss_yahoo"
    )

    author: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Article author if available"
    )

    published_at: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Publication timestamp from the source"
    )

    # ── Ticker symbols ────────────────────────────────────
    #
    # Which stocks this article mentions.
    # Stored as comma-separated string: "AAPL,MSFT,GOOGL"
    #
    # Filled in two stages:
    # Stage 1 (here, Phase 2): news_fetcher.py sets the
    #   symbol it searched for: ticker_symbols = "AAPL"
    # Stage 2 (Phase 3): spaCy NER scans the full body
    #   and adds any other tickers it finds
    ticker_symbols: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        index=True,
        comment="Comma-separated tickers: AAPL,MSFT — enriched by Phase 3"
    )

    # ── Sentiment fields ──────────────────────────────────
    #
    # These are NULL when first saved (Phase 2 just stores).
    # Phase 3 sentence-transformers model fills these in.
    #
    # sentiment_score: -1.0 (very negative) → +1.0 (very positive)
    # sentiment_label: "positive" / "negative" / "neutral"
    sentiment_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Sentiment score -1.0 to +1.0 — filled by Phase 3"
    )

    sentiment_label: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="positive / negative / neutral — filled by Phase 3"
    )

    # ── Embedding flag ────────────────────────────────────
    #
    # Phase 4 RAG layer converts article body to a
    # 384-dimension vector and stores it in pgvector.
    # This flag tracks which articles have been embedded.
    # False = not yet embedded → Phase 4 needs to process
    # True  = already embedded → Phase 4 can skip
    is_embedded: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
        nullable=False,
        comment="True when Phase 4 has created pgvector embedding"
    )

    # ── Composite index ───────────────────────────────────
    #
    # Speeds up the most common query pattern used by
    # Phase 3 and the dashboard:
    # "get all articles about AAPL from the last 7 days"
    #
    # Without this: Postgres scans every row → slow
    # With this:    Postgres jumps directly   → fast
    __table_args__ = (
        Index(
            "ix_news_ticker_published",
            "ticker_symbols",
            "published_at"
        ),
    )

    def __repr__(self) -> str:
        return f"<NewsArticle {self.source}: {self.headline[:50]}>"