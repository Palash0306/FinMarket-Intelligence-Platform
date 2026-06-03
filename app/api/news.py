# path: app/api/news.py

# =========================================================
# NEWS API — Endpoints to read RDS news + sentiment data
# =========================================================
#
# What does this file do in plain English?
#
# This is the front door to your news and sentiment data.
# It reads articles from RDS news_articles table and
# Stocktwits posts from RDS stocktwits_posts table.
# Both were populated by the consumers in Day 2.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# app/db/session.py ───────────────────────────────────┐
#   get_db() → RDS session for SQLAlchemy queries       │
#       ↓                                              │
# app/models/news.py ──────────────────────────────────┤
#   NewsArticle → query news_articles table            │
#       ↓                                              │
# app/models/stocktwits_post.py ───────────────────────┤
#   StocktwitsPost → query stocktwits_posts table      │
#       ↓                                              │
# app/models/stock.py ─────────────────────────────────┤
#   Stock → validate symbol exists                     │
#       ↓                                              │
# app/schemas/news.py ─────────────────────────────────┤
#   NewsArticleResponse → shape article data           │
#   SentimentResponse   → shape sentiment data         │
#       ↓                                              │
# THIS FILE (news.py) ─────────────────────────────────┘
#   defines the HTTP endpoints
#       ↓ registered in
# app/main.py → app.include_router(news_router)
#       ↓ called by
# Streamlit dashboard (Phase 5)
# Phase 4 RAG agent (also reads RDS directly)
#
# DATA FLOW:
#
# GET /api/news/AAPL
#       ↓
# session.py opens RDS connection
#       ↓
# NewsArticle model: SELECT * FROM news_articles
#                    WHERE ticker_symbols LIKE '%AAPL%'
#       ↓
# NewsListResponse schema wraps results
#       ↓
# JSON to user
#
# GET /api/sentiment/AAPL
#       ↓
# StocktwitsPost model: SELECT date, AVG(score)
#                       FROM stocktwits_posts
#                       WHERE ticker_symbol = 'AAPL'
#                       GROUP BY date
#       ↓
# SentimentResponse schema wraps results
#       ↓
# JSON to user
# ─────────────────────────────────────────────────────────

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.db.session import get_db
from app.models.news import NewsArticle
from app.models.stocktwits_post import StocktwitsPost
from app.models.stock import Stock
from app.schemas.news import (
    NewsListResponse,
    NewsArticleResponse,
    SentimentResponse,
    SentimentDataPoint
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/news",
    tags=["News & Sentiment"]
)


def validate_symbol(symbol: str, db: Session) -> Stock:
    """
    Validates symbol exists in RDS stocks table.
    Same helper pattern as prices.py.

    Connects to:
    session.py → db session
    Stock model → stocks table
    """
    stock = db.query(Stock).filter(
        Stock.symbol == symbol.upper(),
        Stock.is_active == True
    ).first()

    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol '{symbol.upper()}' not found or not active"
        )
    return stock


# =========================================================
# GET /api/news/{symbol} — articles for a stock
# =========================================================
@router.get(
    "/{symbol}",
    response_model=NewsListResponse,
    summary="Get news articles for a stock"
)
def get_news_for_symbol(
    symbol: str,
    # limit: max articles to return
    # default 20, max 100
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Max number of articles to return"
    ),
    # source filter: optional filter by source
    # e.g. ?source=newsapi or ?source=rss_reuters
    source: str = Query(
        default=None,
        description="Filter by source: newsapi / rss_reuters / rss_yahoo"
    ),
    db: Session = Depends(get_db)
):
    """
    Returns latest news articles mentioning a stock.

    How it searches:
    Uses LIKE '%AAPL%' on ticker_symbols column.
    This finds articles where "AAPL" appears anywhere
    in the comma-separated ticker_symbols string.

    Example: ticker_symbols = "AAPL,MSFT,GOOGL"
    → found by both /api/news/AAPL and /api/news/MSFT

    Connects to:
    session.py → db connection
    NewsArticle model → news_articles table
    NewsListResponse → schemas/news.py
    """

    validate_symbol(symbol, db)

    # ── Build query ───────────────────────────────────────
    #
    # db.query(NewsArticle) = SELECT * FROM news_articles
    # .filter(...) = adds WHERE conditions
    # .order_by(...) = ORDER BY published_at DESC (newest first)
    # .limit(limit) = LIMIT 20
    query = db.query(NewsArticle).filter(
        # ilike = case-insensitive LIKE
        # '%AAPL%' = contains "AAPL" anywhere in the string
        NewsArticle.ticker_symbols.ilike(f"%{symbol.upper()}%")
    )

    # Apply optional source filter
    if source:
        query = query.filter(
            NewsArticle.source == source
        )

    # Order by published_at descending — newest first
    # Then by created_at as tiebreaker
    articles = query.order_by(
        NewsArticle.published_at.desc(),
        NewsArticle.created_at.desc()
    ).limit(limit).all()

    logger.info(
        "news_fetched",
        extra={
            "symbol": symbol,
            "count": len(articles),
            "source": source
        }
    )

    return NewsListResponse(
        symbol=symbol.upper(),
        total=len(articles),
        articles=articles
    )


# =========================================================
# GET /api/news/ — latest news across all stocks
# =========================================================
@router.get(
    "/",
    response_model=NewsListResponse,
    summary="Get latest news across all tracked stocks"
)
def get_all_news(
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Max articles to return"
    ),
    source: str = Query(
        default=None,
        description="Filter by source"
    ),
    db: Session = Depends(get_db)
):
    """
    Returns latest news across all tracked stocks.

    Used by the dashboard overview page to show
    a general news feed.

    Connects to:
    NewsArticle model → queries news_articles table
    No symbol filter → returns all recent articles
    """

    query = db.query(NewsArticle)

    if source:
        query = query.filter(NewsArticle.source == source)

    articles = query.order_by(
        NewsArticle.created_at.desc()
    ).limit(limit).all()

    return NewsListResponse(
        symbol=None,
        total=len(articles),
        articles=articles
    )


# =========================================================
# GET /api/news/{symbol}/sentiment — sentiment for a stock
# =========================================================
@router.get(
    "/{symbol}/sentiment",
    response_model=SentimentResponse,
    summary="Get Stocktwits sentiment for a stock"
)
def get_sentiment_for_symbol(
    symbol: str,
    days: int = Query(
        default=7,
        ge=1,
        le=30,
        description="Number of days of sentiment history"
    ),
    db: Session = Depends(get_db)
):
    """
    Returns aggregated daily sentiment from Stocktwits.

    What it does:
    1. Queries RDS stocktwits_posts for the symbol
    2. Groups by date
    3. Calculates: avg score, bullish count, bearish count
    4. Returns as time series for charting

    The sentiment_score in stocktwits_posts was already
    set by stocktwits_fetcher.py at ingestion time:
    Bullish → +1.0, Bearish → -1.0, None → 0.0

    So this endpoint just aggregates what's already there.
    Phase 3 will do more sophisticated aggregation —
    this is the simple version for the dashboard.

    Connects to:
    StocktwitsPost model → stocktwits_posts table
    SentimentResponse → schemas/news.py
    sentiment_consumer.py wrote the data (Day 2)
    """

    validate_symbol(symbol, db)

    from datetime import datetime, timedelta, timezone

    # Calculate the start date for the query
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # ── Query and aggregate ───────────────────────────────
    #
    # func.date() extracts date from timestamp string
    # func.avg() = SQL AVG()
    # func.count() = SQL COUNT()
    # case() = SQL CASE WHEN ... THEN ... END
    #
    # This single query replaces what would be many Python loops.
    # SQLAlchemy translates it to SQL automatically.
    daily_data = db.query(
        # Extract just the date part from posted_at
        func.date(StocktwitsPost.posted_at).label("date"),

        # Average sentiment score for that day
        func.avg(StocktwitsPost.sentiment_score).label("avg_score"),

        # Total posts that day
        func.count(StocktwitsPost.id).label("post_count"),

        # Count of Bullish posts
        func.sum(
            case(
                (StocktwitsPost.sentiment_label == "bullish", 1),
                else_=0
            )
        ).label("bullish_count"),

        # Count of Bearish posts
        func.sum(
            case(
                (StocktwitsPost.sentiment_label == "bearish", 1),
                else_=0
            )
        ).label("bearish_count"),

    ).filter(
        StocktwitsPost.ticker_symbol == symbol.upper(),
        StocktwitsPost.posted_at >= start_date.isoformat()
    ).group_by(
        func.date(StocktwitsPost.posted_at)
    ).order_by(
        func.date(StocktwitsPost.posted_at).asc()
    ).all()

    # ── Build time series data points ─────────────────────
    data_points = []
    for row in daily_data:
        avg_score = float(row.avg_score or 0.0)

        # Determine overall label for this day
        if avg_score > 0.1:
            label = "bullish"
        elif avg_score < -0.1:
            label = "bearish"
        else:
            label = "neutral"

        data_points.append(
            SentimentDataPoint(
                date=str(row.date),
                avg_score=round(avg_score, 4),
                post_count=row.post_count,
                bullish_count=int(row.bullish_count or 0),
                bearish_count=int(row.bearish_count or 0),
                label=label
            )
        )

    # ── Calculate overall sentiment for the period ────────
    if data_points:
        overall_score = round(
            sum(d.avg_score for d in data_points) / len(data_points),
            4
        )
    else:
        overall_score = 0.0

    if overall_score > 0.1:
        overall_label = "bullish"
    elif overall_score < -0.1:
        overall_label = "bearish"
    else:
        overall_label = "neutral"

    logger.info(
        "sentiment_fetched",
        extra={
            "symbol": symbol,
            "days": days,
            "overall": overall_label
        }
    )

    return SentimentResponse(
        symbol=symbol.upper(),
        period_days=days,
        overall_score=overall_score,
        overall_label=overall_label,
        data=data_points
    )