# path: app/db/clickhouse.py

# =========================================================
# CLICKHOUSE CONNECTION
# =========================================================
#
# What is ClickHouse in plain English?
#
# Imagine you have a spreadsheet with 10 million rows of
# stock prices. If you ask Excel "what was the average
# closing price of AAPL every hour for the last 90 days"
# it would freeze for minutes.
#
# ClickHouse answers that same question in milliseconds.
# It's built specifically for this — huge amounts of
# numerical data, read very fast.
#
# We use it ONLY for price data (time-series).
# News articles, stocks, forecasts stay in Postgres/RDS.
#
# Why separate databases?
# Right tool for right job:
# - Postgres: good at relationships, joins, searches
# - ClickHouse: good at aggregations over time (avg, sum, count)

from clickhouse_driver import Client
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def get_clickhouse_client() -> Client:
    """
    Creates and returns a ClickHouse client connection.

    Unlike SQLAlchemy (which has a pool), ClickHouse
    connections are lightweight — we create one per operation.

    In plain English: opens a direct line to ClickHouse,
    you use it, then it closes. No pooling needed because
    ClickHouse queries are so fast.
    """
    return Client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=settings.clickhouse_db,
        user=settings.clickhouse_user,
        password=settings.clickhouse_password
    )


def init_clickhouse_tables() -> None:
    """
    Creates ClickHouse tables if they don't exist.

    Called once at app startup.

    Think of this like Alembic for ClickHouse —
    but simpler because ClickHouse uses
    CREATE TABLE IF NOT EXISTS (no migration files needed).
    """
    client = get_clickhouse_client()

    try:
        # ── OHLCV Table ───────────────────────────────────
        #
        # OHLCV = Open, High, Low, Close, Volume
        # This is the standard format for stock price data.
        #
        # Every row = one price snapshot for one stock
        # at one point in time.
        #
        # MergeTree engine:
        # ClickHouse's default engine. Stores data sorted
        # by (symbol, timestamp) — makes time-range queries
        # blazing fast because related data sits together on disk.
        #
        # PARTITION BY toYYYYMM(timestamp):
        # Splits data into monthly chunks.
        # When you query "last 7 days", ClickHouse only
        # reads the current month's chunk — ignores the rest.
        client.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol      String,
                timestamp   DateTime,
                open        Float64,
                high        Float64,
                low         Float64,
                close       Float64,
                volume      Float64,
                source      String DEFAULT 'yfinance'
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (symbol, timestamp)
        """)

        # ── Sentiment Scores Table ────────────────────────
        #
        # Stores aggregated daily sentiment per ticker.
        # ML models in Phase 3 read from this.
        #
        # score range: -1.0 (very negative) to +1.0 (very positive)
        # article_count: how many articles contributed to the score
        client.execute("""
            CREATE TABLE IF NOT EXISTS daily_sentiment (
                symbol          String,
                date            Date,
                avg_score       Float64,
                article_count   UInt32,
                source          String
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(date)
            ORDER BY (symbol, date)
        """)

        logger.info("clickhouse_tables_initialized")

    except Exception as e:
        logger.error(f"clickhouse_init_error: {e}")
        raise


def check_clickhouse_connection() -> bool:
    """
    Simple health check — returns True if ClickHouse is alive.
    Used by the /health endpoint in Phase 5.
    """
    try:
        client = get_clickhouse_client()
        client.execute("SELECT 1")
        return True
    except Exception:
        return False