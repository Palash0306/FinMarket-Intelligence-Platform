# path: app/ingestion/stock_fetcher.py

# =========================================================
# STOCK PRICE FETCHER
# =========================================================
#
# What does this file do in plain English?
#
# Every 5 minutes, this goes to Yahoo Finance (via yfinance),
# downloads the latest price for every stock in our database,
# saves the raw data to S3, then publishes a message to Kafka
# saying "hey, new price data is here, go process it."
#
# It NEVER writes to ClickHouse directly.
# That's the consumer's job (price_consumer.py).
#
# Why this separation?
# Fetcher just collects. Consumer just stores.
# If the consumer crashes, the fetcher keeps running.
# Messages wait safely in Kafka. When consumer restarts,
# it processes everything it missed. No data lost.
#
# Connection to Phase 1:
# - Reads the stocks table from RDS (via session.py)
#   to know which symbols to fetch
# - Uses S3Helper to archive raw data
# - Uses config.py for settings

# Day 1 flow (already working):
#   Celery→ stock_fetcher.py → Kafka("market.prices") → price_consumer.py → ClickHouse

import json
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone
from confluent_kafka import Producer
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.stock import Stock
from app.ingestion.s3_helper import s3_helper
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class StockFetcher:
    """
    Fetches real-time stock price data using yfinance.

    yfinance wraps Yahoo Finance — completely free,
    no API key, no rate limits for reasonable usage.

    In plain English: this is the scout that goes out
    to Yahoo Finance and brings back prices.
    """

    def __init__(self):
        # ── Kafka Producer ────────────────────────────────
        #
        # Producer = the sender side of Kafka.
        # It sends messages to Kafka topics.
        #
        # Think of it as: someone who drops letters
        # in the postal box (Kafka)
        self.producer = Producer({
            "bootstrap.servers": settings.kafka_bootstrap_servers
        })

    def get_active_symbols(self) -> list[str]:
        """
        Gets list of active stock symbols from RDS.

        Reads the stocks table we seeded in Phase 1.
        Returns ["AAPL", "MSFT", "GOOGL", ...] etc.

        Connection to Phase 1:
        Uses SessionLocal from session.py and
        Stock model from models/stock.py
        """
        db: Session = SessionLocal()
        try:
            stocks = db.query(Stock).filter(
                Stock.is_active == True
            ).all()
            return [stock.symbol for stock in stocks]
        finally:
            db.close()

    def fetch_current_prices(self) -> dict:
        """
        Fetches current price data for all active stocks.

        Uses yfinance 1.4.1+ which requires different
        column access than the old 0.2.x version.

        Connection chain:
        RDS stocks table → symbols list
        yfinance → Yahoo Finance prices
        → returns dict of symbol → price data
        → fetch_and_publish() saves to S3 + Kafka
        → price_consumer.py writes to ClickHouse ohlcv
        """
        symbols = self.get_active_symbols()

        if not symbols:
            logger.warning("no_active_symbols_found")
            return {}

        logger.info(
            "fetching_prices",
            extra={"symbols": symbols, "count": len(symbols)}
        )

        results = {}

        for symbol in symbols:
            try:
                # ── Fetch using new yfinance 1.4.1 API ───────
                #
                # Ticker.history() still works in 1.4.1
                # but column names changed slightly.
                # We use period="1d" for last trading day
                # interval="5m" for 5-minute candles
                ticker = yf.Ticker(symbol)
                hist = ticker.history(
                    period="1d",
                    interval="5m",
                    auto_adjust=True  # adjust for splits/dividends
                )

                if hist.empty:
                    # Try with longer period as fallback
                    # (market might be closed today)
                    hist = ticker.history(
                        period="5d",
                        interval="1d",
                        auto_adjust=True
                    )

                if hist.empty:
                    logger.warning(
                        "no_price_data",
                        extra={"symbol": symbol}
                    )
                    continue

                # ── Get latest row ────────────────────────────
                latest = hist.iloc[-1]

                # ── Safely extract float values ───────────────
                #
                # yfinance 1.4.1 sometimes returns Series
                # instead of scalar values. .item() converts
                # any numpy type to a plain Python float.
                def safe_float(val) -> float:
                    try:
                        if hasattr(val, 'item'):
                            return round(float(val.item()), 4)
                        return round(float(val), 4)
                    except Exception:
                        return 0.0

                price_data = {
                    "symbol":    symbol,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "open":      safe_float(latest["Open"]),
                    "high":      safe_float(latest["High"]),
                    "low":       safe_float(latest["Low"]),
                    "close":     safe_float(latest["Close"]),
                    "volume":    safe_float(latest["Volume"]),
                    "source":    "yfinance"
                }

                results[symbol] = price_data
                logger.info(
                    "price_fetched",
                    extra={
                        "symbol": symbol,
                        "close": price_data["close"]
                    }
                )

            except Exception as e:
                logger.error(
                    "price_fetch_error",
                    extra={"symbol": symbol, "error": str(e)}
                )
                continue

        return results

    def fetch_and_publish(self) -> int:
        """
        Main method called by Celery every 5 minutes.

        Does three things:
        1. Fetch prices from Yahoo Finance
        2. Save raw data to S3
        3. Publish to Kafka topic "market.prices"

        Returns count of successfully processed symbols.
        """

        # ── Step 1: Fetch prices ──────────────────────────
        prices = self.fetch_current_prices()

        if not prices:
            return 0

        # ── Step 2: Save raw batch to S3 ─────────────────
        #
        # Archive the entire batch as one JSON file.
        # Path: prices/2024-01-15/batch_093000.json
        try:
            s3_helper.save_raw_data(
                data=prices,
                data_type="prices",
                identifier="batch"
            )
        except Exception as e:
            # S3 failure should NOT stop Kafka publishing
            # Log it but continue
            logger.error(f"s3_save_failed_continuing: {e}")

        # ── Step 3: Publish each price to Kafka ──────────
        #
        # We publish one message per symbol.
        # Why not one big message?
        # Consumers can process symbols independently and
        # in parallel — faster, more resilient.
        published = 0
        for symbol, price_data in prices.items():
            try:
                self.producer.produce(
                    # topic = "market.prices"
                    # Think of it as the address on the envelope
                    topic="market.prices",

                    # key = symbol — used by Kafka to route
                    # messages to the same partition
                    # (all AAPL messages go to same partition)
                    key=symbol.encode("utf-8"),

                    # value = the actual price data as JSON bytes
                    value=json.dumps(price_data).encode("utf-8")
                )
                published += 1

            except Exception as e:
                logger.error(
                    "kafka_publish_error",
                    extra={"symbol": symbol, "error": str(e)}
                )

        # ── Flush ensures all messages are sent ──────────
        #
        # producer.produce() queues messages locally.
        # producer.flush() actually sends them to Kafka.
        # Like pressing "send" on a batch of emails.
        self.producer.flush()

        logger.info(
            "prices_published",
            extra={"published": published, "total": len(prices)}
        )

        return published


# Single instance — created once, reused by Celery tasks
stock_fetcher = StockFetcher()