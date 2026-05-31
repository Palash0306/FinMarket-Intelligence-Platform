# path: app/models/stocktwits_post.py

# =========================================================
# STOCKTWITS POST MODEL
# =========================================================
#
# What is this file in plain English?
#
# This defines the stocktwits_posts TABLE in RDS.
# One row = one post from Stocktwits about a stock.
#
# Stocktwits is like Twitter but ONLY for stock traders.
# Every post is tagged with a ticker symbol like $AAPL.
# Users voluntarily label their own posts as:
# - Bullish  = they think the price will go UP
# - Bearish  = they think the price will go DOWN
#
# This pre-labelled sentiment is incredibly valuable.
# It means Phase 3 doesn't need to guess sentiment
# for Stocktwits posts — it's already there.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO EVERYTHING ELSE:
#
# Stocktwits API (free, no key)
#       ↓ fetched by
# stocktwits_fetcher.py
#       ↓ converts "Bullish"/"Bearish" to +1.0/-1.0
#       ↓ publishes to
# Kafka "sentiment.raw" topic
#       ↓ consumed by
# sentiment_consumer.py
#       ↓ uses THIS MODEL to insert rows into
# RDS stocktwits_posts table
#       ↓ read by
# Phase 3 ── aggregates avg sentiment per ticker per day
#             writes results to ClickHouse daily_sentiment
# Phase 4 ── embeds post body into pgvector for AI search
#
# KEY DIFFERENCE FROM NEWS MODEL:
#
# NewsArticle:      sentiment_score = NULL at ingestion
#                   Phase 3 fills it later
#
# StocktwitsPost:   sentiment_score = FILLED at ingestion
#                   Stocktwits users pre-label their posts
#                   Phase 3 just aggregates, doesn't score
# ─────────────────────────────────────────────────────────

from sqlalchemy import Integer, String, Float, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class StocktwitsPost(Base, TimestampMixin):
    """
    Represents one Stocktwits message about a stock.

    Key advantage over news articles:
    sentiment_score is filled at ingestion time using
    the user's own Bullish/Bearish label — no ML needed.

    Table: stocktwits_posts
    """

    __tablename__ = "stocktwits_posts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="Auto-incrementing row ID"
    )

    # ── Stocktwits own message ID ─────────────────────────
    #
    # Deduplication key — same role as url in NewsArticle.
    # If we fetch the same message twice, stocktwits_id
    # lets us detect it and skip the duplicate.
    stocktwits_id: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Stocktwits message ID — deduplication key"
    )

    # ── Message text ──────────────────────────────────────
    #
    # The actual post text.
    # Phase 4 RAG embeds this alongside news article bodies.
    body: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
        comment="Post text — Phase 4 embeds this into pgvector"
    )

    # ── Ticker symbol ─────────────────────────────────────
    #
    # Unlike news articles (which can mention many stocks),
    # each Stocktwits post is tagged to ONE primary symbol.
    # That's how Stocktwits works — you tag $AAPL or $MSFT.
    ticker_symbol: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="Stock this post is about e.g. AAPL"
    )

    author: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Stocktwits username"
    )

    posted_at: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="When posted on Stocktwits"
    )

    # ── Pre-labelled sentiment ────────────────────────────
    #
    # This is what makes Stocktwits data special.
    # Filled at ingestion time by stocktwits_fetcher.py.
    # NOT waiting for Phase 3.
    #
    # sentiment_label: "bullish" / "bearish" / None
    # sentiment_score: +1.0     / -1.0      / 0.0
    #
    # Phase 3 uses sentiment_score directly for aggregation:
    # AVG(sentiment_score) per ticker per day
    # → writes to ClickHouse daily_sentiment table
    sentiment_label: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="bullish / bearish / None — from the user's own label"
    )

    sentiment_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="+1.0 bullish / -1.0 bearish / 0.0 neutral"
    )

    # ── Engagement signal ─────────────────────────────────
    #
    # How many people liked this post.
    # Phase 3 uses this as a WEIGHT in sentiment aggregation.
    # A post with 100 likes is more credible than one with 0.
    # Weighted average: sum(score × likes) / sum(likes)
    liked_count: Mapped[int] = mapped_column(
        default=0,
        comment="Number of likes — used as weight in Phase 3 aggregation"
    )

    __table_args__ = (
        Index(
            "ix_stocktwits_ticker_posted",
            "ticker_symbol",
            "posted_at"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<StocktwitsPost ${self.ticker_symbol} "
            f"{self.sentiment_label}: {str(self.body)[:40]}>"
        )