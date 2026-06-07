# path: app/tasks/scheduled.py

# =========================================================
# SCHEDULED TASK DEFINITIONS
# =========================================================
#
# What is this file in plain English?
#
# This file defines the actual functions Celery runs
# on a schedule. Think of each function as a job
# description — Celery reads the schedule in celery_app.py
# and runs these functions at the right times.
#
# @celery_app.task decorator:
# Turns a normal Python function into a Celery task.
# This means Celery can:
# - Queue it
# - Run it in a worker process
# - Retry it if it fails
# - Track its result

#  Celery Beat → Worker → stock_fetcher.py → Kafka("market.prices") → price_consumer.py → ClickHouse
# path: app/tasks/scheduled.py
# Full replacement — all 3 tasks with proper connections

from app.tasks.celery_app import celery_app
from app.utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(
    name="app.tasks.scheduled.fetch_stock_prices",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60
)
def fetch_stock_prices():
    """
    Runs every 5 minutes.

    Full connection chain:
    ┌──────────────────────────────────────────────────┐
    │ Celery beat triggers this task                   │
    │       ↓                                          │
    │ stock_fetcher.fetch_and_publish()                │
    │       ↓ reads                                    │
    │ RDS stocks table (Phase 1)                       │
    │       ↓ fetches from                             │
    │ yfinance → Yahoo Finance (free, no key)          │
    │       ↓ archives to                              │
    │ S3 prices/date/batch.json                        │
    │       ↓ publishes to                             │
    │ Kafka "market.prices"                            │
    │       ↓ consumed by                              │
    │ price_consumer.py (Day 1)                        │
    │       ↓ writes to                                │
    │ ClickHouse ohlcv table                           │
    │       ↓ read by Phase 3                          │
    │ Prophet forecasting model                        │
    │ XGBoost signal classifier                        │
    └──────────────────────────────────────────────────┘
    """
    from app.ingestion.stock_fetcher import stock_fetcher
    logger.info("task_started: fetch_stock_prices")
    count = stock_fetcher.fetch_and_publish()
    logger.info(
        "task_completed: fetch_stock_prices",
        extra={"symbols_published": count}
    )
    return {"symbols_published": count}


@celery_app.task(
    name="app.tasks.scheduled.fetch_news_articles",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=120
)
def fetch_news_articles():
    """
    Runs every 30 minutes.

    Full connection chain:
    ┌──────────────────────────────────────────────────┐
    │ Celery beat triggers this task                   │
    │       ↓                                          │
    │ news_fetcher.fetch_and_publish()                 │
    │       ↓ reads                                    │
    │ RDS stocks table (Phase 1)                       │
    │       ↓ fetches from                             │
    │ NewsAPI (100 req/day free) + RSS feeds (free)    │
    │       ↓ archives to                              │
    │ S3 news/date/batch.json                          │
    │       ↓ publishes to                             │
    │ Kafka "news.raw"                                 │
    │       ↓ consumed by                              │
    │ news_consumer.py                                 │
    │       ↓ deduplicates by URL                      │
    │       ↓ writes to                               │
    │ RDS news_articles table                          │
    │       ↓ read by Phase 3                          │
    │ spaCy NER → fills ticker_symbols                 │
    │ sentiment model → fills sentiment_score          │
    │       ↓ read by Phase 4                          │
    │ RAG embeddings → fills is_embedded               │
    └──────────────────────────────────────────────────┘
    """
    from app.ingestion.news_fetcher import news_fetcher
    logger.info("task_started: fetch_news_articles")
    count = news_fetcher.fetch_and_publish()
    logger.info(
        "task_completed: fetch_news_articles",
        extra={"articles_published": count}
    )
    return {"articles_published": count}


# path: app/tasks/scheduled.py
# Find fetch_stocktwits_sentiment and replace with:

@celery_app.task(
    name="app.tasks.scheduled.fetch_stocktwits_sentiment",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=300
)
def fetch_stocktwits_sentiment():
    """
    Runs every hour.
    Now uses yfinance news + Alpha Vantage instead of
    Stocktwits (which is Cloudflare blocked).

    Connection chain:
    Celery beat
        ↓
    sentiment_fetcher.fetch_and_publish()
        ↓ reads symbols from RDS stocks table
        ↓ fetches from yfinance news (free, no key)
        ↓ fetches from Alpha Vantage news (free, 25/day)
        ↓ scores headlines as bullish/bearish/neutral
        ↓ archives to S3
        ↓ publishes to Kafka "sentiment.raw"
        ↓
    sentiment_consumer.py
        ↓ writes to RDS stocktwits_posts table
    """
    # Import new fetcher instead of stocktwits_fetcher
    from app.ingestion.sentiment_fetcher import sentiment_fetcher
    logger.info("task_started: fetch_sentiment")
    count = sentiment_fetcher.fetch_and_publish()
    logger.info(
        "task_completed: fetch_sentiment",
        extra={"messages_published": count}
    )
    return {"messages_published": count}


@celery_app.task(
    name="app.tasks.scheduled.run_forecasting",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=300
)
def run_forecasting():
    """
    Runs daily at 9am UTC.
    Trains Prophet + XGBoost for ALL active symbols.

    Connection chain:
    Celery beat (daily 9am)
        ↓
    get active symbols from RDS stocks table
        ↓
    run_prophet_forecast(symbol) per symbol
        ↓ reads from ClickHouse ohlcv
        ↓ saves to RDS forecasts table
        ↓ logs to MLflow

    run_xgb_forecast(symbol) per symbol
        ↓ reads from ClickHouse ohlcv
        ↓ builds features (feature_engineering.py)
        ↓ saves to RDS forecasts table
        ↓ logs to MLflow
    """
    from app.ml.forecasting.prophet_model import run_prophet_forecast
    from app.ml.forecasting.xgb_model import run_xgb_forecast
    from app.db.session import SessionLocal
    from app.models.stock import Stock

    logger.info("task_started: run_forecasting")

    db = SessionLocal()
    try:
        symbols = [
            s.symbol for s in
            db.query(Stock).filter(Stock.is_active == True).all()
        ]
    finally:
        db.close()

    results = []
    for symbol in symbols:
        prophet_result = run_prophet_forecast(symbol)
        xgb_result     = run_xgb_forecast(symbol)
        results.append({
            "symbol":  symbol,
            "prophet": prophet_result.get("status"),
            "xgb":     xgb_result.get("status")
        })
        logger.info(
            "symbol_forecast_done",
            extra={"symbol": symbol}
        )

    logger.info(
        "task_completed: run_forecasting",
        extra={"total": len(results)}
    )
    return {"forecasted": len(results), "results": results}