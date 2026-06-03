# path: app/schemas/news.py

# =========================================================
# NEWS + SENTIMENT SCHEMAS
# =========================================================
#
# What is this file in plain English?
#
# Defines the shape of news and sentiment data
# that comes OUT of your API.
#
# Two types of data exposed here:
# 1. News articles  → from RDS news_articles table
# 2. Sentiment      → from RDS stocktwits_posts table
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# RDS news_articles table ─────────────────────────────┐
# (written by news_consumer.py Day 2)                  │
#       ↓ raw NewsArticle objects from SQLAlchemy       │
# app/api/news.py                                      │
#       ↓ wraps each article in                        │
# NewsArticleResponse ─────────────────────────────────┘
#       ↓ sent to browser
#
# RDS stocktwits_posts table ──────────────────────────┐
# (written by sentiment_consumer.py Day 2)             │
#       ↓ raw StocktwitsPost objects from SQLAlchemy    │
# app/api/news.py                                      │
#       ↓ aggregates and wraps in                      │
# SentimentResponse ───────────────────────────────────┘
#       ↓ sent to browser
#
# Phase 5 Dashboard reads these endpoints
# to show news feed and sentiment charts
# ─────────────────────────────────────────────────────────

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class NewsArticleResponse(BaseModel):
    """
    Shape of ONE news article returned by the API.

    Maps directly to NewsArticle model fields
    from app/models/news.py — but only exposes
    the fields that are safe and useful to the user.

    Fields NOT exposed (internal):
    - is_embedded (Phase 4 internal flag)
    - created_at / updated_at (internal timestamps)

    Connects to:
    NewsArticle SQLAlchemy model → fields match exactly
    news_consumer.py wrote them → news.py reads them
    """

    id:              int
    url:             str
    headline:        str
    body:            Optional[str] = None
    source:          str
    author:          Optional[str] = None
    published_at:    Optional[str] = None

    # ticker_symbols: which stocks this article mentions
    # Set by news_fetcher.py at ingestion time
    # Enriched by Phase 3 spaCy NER
    ticker_symbols:  Optional[str] = None

    # sentiment fields:
    # NULL right now — Phase 3 fills them in
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None

    model_config = {"from_attributes": True}


class NewsListResponse(BaseModel):
    """
    Wraps a list of news articles with metadata.

    Response shape:
    {
      "symbol": "AAPL",
      "total": 42,
      "articles": [ {...}, {...} ]
    }

    Same pattern as StockListResponse from Phase 1 —
    always wrap lists in an object so we can add
    metadata (total count, pagination) without
    breaking the API contract later.
    """

    symbol:   Optional[str] = None
    total:    int
    articles: list[NewsArticleResponse]


class SentimentDataPoint(BaseModel):
    """
    One data point in a sentiment time series.

    Represents the AVERAGE sentiment for one symbol
    on one day — aggregated from many Stocktwits posts.

    Connects to:
    RDS stocktwits_posts → news.py runs AVG query
    → grouped by ticker_symbol + date
    → each group becomes one SentimentDataPoint
    """

    date:          str
    avg_score:     float = Field(
        description="Average sentiment -1.0 to +1.0"
    )
    post_count:    int = Field(
        description="How many posts contributed to this average"
    )
    bullish_count: int = Field(
        description="Posts labelled bullish"
    )
    bearish_count: int = Field(
        description="Posts labelled bearish"
    )
    # Overall label for the day
    # "bullish" if avg_score > 0.1
    # "bearish" if avg_score < -0.1
    # "neutral" otherwise
    label:         str


class SentimentResponse(BaseModel):
    """
    Full sentiment response for one symbol.

    Response shape:
    {
      "symbol": "AAPL",
      "period_days": 7,
      "overall_score": 0.35,
      "overall_label": "bullish",
      "data": [ {...}, {...} ]
    }
    """

    symbol:        str
    period_days:   int
    overall_score: float
    overall_label: str

    # data: list of daily sentiment points
    # Used by the dashboard to draw a sentiment chart
    data: list[SentimentDataPoint]