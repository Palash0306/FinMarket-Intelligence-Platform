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


@celery_app.task(
    name="app.tasks.scheduled.fetch_stocktwits_sentiment",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=300
)
def fetch_stocktwits_sentiment():
    """
    Runs every hour.

    Full connection chain:
    ┌──────────────────────────────────────────────────┐
    │ Celery beat triggers this task                   │
    │       ↓                                          │
    │ stocktwits_fetcher.fetch_and_publish()           │
    │       ↓ reads                                    │
    │ RDS stocks table (Phase 1)                       │
    │       ↓ fetches from                             │
    │ Stocktwits API (free, NO API KEY needed)         │
    │ GET /streams/symbol/AAPL.json per symbol         │
    │       ↓ converts                                 │
    │ "Bullish" → +1.0, "Bearish" → -1.0              │
    │       ↓ archives to                              │
    │ S3 sentiment/date/batch.json                     │
    │       ↓ publishes to                             │
    │ Kafka "sentiment.raw"                            │
    │       ↓ consumed by                              │
    │ sentiment_consumer.py                            │
    │       ↓ deduplicates by stocktwits_id            │
    │       ↓ writes to                                │
    │ RDS stocktwits_posts table                       │
    │ (sentiment_score ALREADY filled here)            │
    │       ↓ read by Phase 3                          │
    │ RDS news_articles ──┐                            │
    │                     ├→ sentiment_aggregator.py   │
    │ RDS stocktwits ─────┘  AVG(score) per ticker/day │
    │                         → ClickHouse daily_sentiment│
    └──────────────────────────────────────────────────┘
    """
    from app.ingestion.stocktwits_fetcher import stocktwits_fetcher
    logger.info("task_started: fetch_stocktwits_sentiment")
    count = stocktwits_fetcher.fetch_and_publish()
    logger.info(
        "task_completed: fetch_stocktwits_sentiment",
        extra={"messages_published": count}
    )
    return {"messages_published": count}