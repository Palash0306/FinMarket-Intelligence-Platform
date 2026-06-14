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
    │       ↓ writes to                                │
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



@celery_app.task(
    name="app.tasks.scheduled.run_sentiment_nlp",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=120
)
def run_sentiment_nlp():
    """
    Runs every 30 minutes.

    Connection chain:
    Celery beat
        ↓
    ner_pipeline.run_ner_pipeline()
        ↓ reads news_articles where ticker=NULL
        ↓ spaCy finds company names
        ↓ maps to ticker symbols
        ↓ updates RDS news_articles.ticker_symbols

    sentiment.run_sentiment_scoring()
        ↓ reads news_articles where score=NULL
        ↓ sentence-transformers scores headline+body
        ↓ updates RDS news_articles.sentiment_score
    """
    from app.ml.nlp.ner_pipeline import run_ner_pipeline
    from app.ml.nlp.sentiment import run_sentiment_scoring

    logger.info("task_started: run_sentiment_nlp")

    ner_result       = run_ner_pipeline(batch_size=100)
    sentiment_result = run_sentiment_scoring(batch_size=100)

    logger.info(
        "task_completed: run_sentiment_nlp",
        extra={
            "ner":       ner_result.get("enriched", 0),
            "sentiment": sentiment_result.get("scored", 0)
        }
    )
    return {
        "ner_enriched":    ner_result.get("enriched", 0),
        "sentiment_scored": sentiment_result.get("scored", 0)
    }


@celery_app.task(
    name="app.tasks.scheduled.run_anomaly_check",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60
)
def run_anomaly_check():
    """
    Runs every 15 minutes.

    Connection chain:
    Celery beat
        ↓
    detector.run_anomaly_detection()
        ↓ reads ClickHouse ohlcv (last 60 days)
        ↓ calculates z-scores for price + volume
        ↓ detects statistically unusual events
        ↓ saves to RDS anomalies table
        ↓ Phase 5 reads anomalies → sends alerts
    """
    from app.ml.anomaly.detector import run_anomaly_detection

    logger.info("task_started: run_anomaly_check")
    result = run_anomaly_detection()
    logger.info(
        "task_completed: run_anomaly_check",
        extra={"anomalies_found": result.get("anomalies_found", 0)}
    )
    return result


@celery_app.task(
    name="app.tasks.scheduled.run_embeddings",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=300
)
def run_embeddings():
    """
    Runs every hour.

    Connection chain:
    Celery beat
        ↓
    embed_news.run_embedding_pipeline()
        ↓ reads news_articles where is_embedded=False
        ↓ sentence-transformers encodes text → 384-dim vector
        ↓ stores vector in pgvector column
        ↓ sets is_embedded=True
        ↓ Phase 4 RAG uses vectors for semantic search
    """
    from app.ml.embeddings.embed_news import run_embedding_pipeline

    logger.info("task_started: run_embeddings")
    result = run_embedding_pipeline(batch_size=50)
    logger.info(
        "task_completed: run_embeddings",
        extra={"embedded": result.get("embedded", 0)}
    )
    return result


@celery_app.task(
    name="app.tasks.scheduled.run_alert_check",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60
)
def run_alert_check():
    """
    Runs every 15 minutes alongside anomaly detection.

    Connection chain:
    Celery beat
        ↓
    alert_service.run_alert_check()
        ↓ reads RDS anomalies where is_alerted=False
        ↓ sends email via AWS SES
        ↓ sets is_alerted=True
    """
    from app.services.alert_service import run_alert_check
    logger.info("task_started: run_alert_check")
    result = run_alert_check()
    logger.info(
        "task_completed: run_alert_check",
        extra={"sent": result.get("sent", 0)}
    )
    return result