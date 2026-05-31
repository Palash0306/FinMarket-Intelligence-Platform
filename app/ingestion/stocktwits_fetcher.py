# path: app/ingestion/stocktwits_fetcher.py

# =========================================================
# STOCKTWITS FETCHER
# =========================================================
#
# What does this file do in plain English?
#
# Every hour, Celery wakes this up.
# It calls the Stocktwits public API for each of our
# tracked stocks — completely free, no API key needed.
# Gets the latest 30 posts tagged with that ticker.
#
# The BIG advantage over Reddit or news:
# Stocktwits users label their own posts Bullish/Bearish.
# We convert those labels to +1.0/-1.0 numbers right here.
# Phase 3 just needs to aggregate — the hard work is done.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO EVERYTHING ELSE:
#
# config.py
#       ↓ KAFKA_BOOTSTRAP_SERVERS
# THIS FILE (stocktwits_fetcher.py)
#       ↓ reads active symbols from
# RDS stocks table ─────────── (Phase 1 session.py + Stock)
#       ↓ calls for each symbol
# Stocktwits API ──────────── (free, no key, no signup)
# https://api.stocktwits.com/api/2/streams/symbol/AAPL.json
#       ↓ converts Bullish→+1.0, Bearish→-1.0
#       ↓ archives raw to
# S3 sentiment/date/batch.json ─── (s3_helper Day 1)
#       ↓ publishes to
# Kafka "sentiment.raw" ─────────── (Kafka Day 1)
#       ↓ consumed by
# sentiment_consumer.py ─────────── (built below)
#       ↓ writes to
# RDS stocktwits_posts table ─────── (model above)
#       ↓ read by
# Phase 3 ── aggregates avg sentiment per ticker per day
#             no scoring needed — score already here
# Phase 4 ── embeds body text into pgvector
# ─────────────────────────────────────────────────────────

import json
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

# ── Stocktwits API endpoint ───────────────────────────────
#
# Public endpoint — no authentication needed.
# Returns last 30 posts for any stock symbol.
# Rate limit: 200 requests/hour (plenty for 10 stocks)
#
# Example response:
# GET /streams/symbol/AAPL.json → last 30 $AAPL posts
STOCKTWITS_BASE_URL = (
    "https://api.stocktwits.com/api/2/streams/symbol"
)

# ── Sentiment conversion map ──────────────────────────────
#
# Stocktwits labels → numeric scores
# Used in fetch_symbol_messages() below
#
# "Bullish" = trader thinks price goes UP   → +1.0
# "Bearish" = trader thinks price goes DOWN → -1.0
# None      = trader didn't label their post → 0.0
SENTIMENT_SCORE_MAP = {
    "bullish":  1.0,
    "bearish": -1.0,
    None:       0.0
}


class StocktwitsFetcher:
    """
    Fetches financial sentiment from Stocktwits.
    Zero setup — no API key, no account needed.

    In plain English: a scout who checks Stocktwits
    every hour and reports back what traders think
    about our stocks, with pre-labelled sentiment.

    Connects to:
    ┌──────────────────────────────────────────────────┐
    │ config.py      → Kafka server address            │
    │ session.py     → DB connection for symbols       │
    │ Stock model    → reads active symbols            │
    │ s3_helper.py   → archives raw posts              │
    │ Kafka Producer → publishes to sentiment.raw      │
    └──────────────────────────────────────────────────┘
    """

    def __init__(self):

        # ── HTTP client ───────────────────────────────────
        #
        # httpx.Client makes HTTP requests.
        # Like a browser built into Python.
        # timeout=10 = give up if Stocktwits doesn't
        # respond within 10 seconds.
        self.http_client = httpx.Client(timeout=10)

        # ── Kafka Producer ────────────────────────────────
        #
        # Identical pattern to stock_fetcher.py (Day 1)
        # and news_fetcher.py (above).
        # Sends to "sentiment.raw" topic instead.
        self.producer = Producer({
            "bootstrap.servers": settings.kafka_bootstrap_servers
        })

    def get_active_symbols(self) -> list[str]:
        """
        Gets active stock symbols from RDS.

        Same pattern used across ALL fetchers:
        ┌────────────────────────────────────────────┐
        │ session.py   → SessionLocal() opens DB     │
        │ Stock model  → queries stocks table        │
        │ Phase 1 data → returns our 10 seed stocks  │
        └────────────────────────────────────────────┘

        Returns ["AAPL", "MSFT", "GOOGL", ...]
        """
        db: Session = SessionLocal()
        try:
            stocks = db.query(Stock).filter(
                Stock.is_active == True
            ).all()
            return [stock.symbol for stock in stocks]
        finally:
            db.close()

    def fetch_symbol_messages(
        self,
        symbol: str
    ) -> list[dict]:
        """
        Fetches latest Stocktwits posts for one symbol.

        Makes one GET request per symbol.
        Returns up to 30 structured message dicts.

        API response structure (simplified):
        {
          "messages": [
            {
              "id": 123456789,
              "body": "AAPL looking strong today!",
              "created_at": "2024-01-15T09:30:00Z",
              "user": {"username": "trader_joe"},
              "entities": {
                "sentiment": {"basic": "Bullish"}
              }
            }
          ]
        }

        We extract and convert:
        "Bullish" → sentiment_label="bullish", score=+1.0
        "Bearish" → sentiment_label="bearish", score=-1.0
        null      → sentiment_label=None,      score= 0.0
        """
        url = f"{STOCKTWITS_BASE_URL}/{symbol}.json"
        messages = []

        try:
            # ── GET request to Stocktwits ─────────────────
            #
            # No headers, no auth token.
            # Completely open public API.
            response = self.http_client.get(url)

            if response.status_code != 200:
                logger.warning(
                    "stocktwits_non_200",
                    extra={
                        "symbol": symbol,
                        "status": response.status_code
                    }
                )
                return []

            data = response.json()

            # ── Process each message ──────────────────────
            for msg in data.get("messages", []):

                # ── Extract pre-labelled sentiment ────────
                #
                # Not all posts have sentiment labels.
                # Stocktwits users optionally tag Bullish/Bearish.
                # entities → sentiment → basic = the label string
                sentiment_raw = (
                    msg.get("entities", {})
                       .get("sentiment")
                )
                sentiment_label = (
                    sentiment_raw.get("basic", "").lower()
                    if sentiment_raw
                    else None
                )

                # ── Convert label to number ───────────────
                #
                # ML models need numbers not strings.
                # Phase 3 does AVG(sentiment_score) per ticker.
                # SENTIMENT_SCORE_MAP defined at top of file:
                # "bullish" → +1.0
                # "bearish" → -1.0
                # None      →  0.0
                sentiment_score = SENTIMENT_SCORE_MAP.get(
                    sentiment_label, 0.0
                )

                # ── Structure into our format ─────────────
                #
                # Normalise Stocktwits field names to
                # match our StocktwitsPost model fields.
                messages.append({
                    "stocktwits_id":   str(msg.get("id", "")),
                    "body":            msg.get("body", ""),
                    "ticker_symbol":   symbol,
                    "author":          msg.get(
                                           "user", {}
                                       ).get("username", "unknown"),
                    "posted_at":       msg.get("created_at", ""),
                    "sentiment_label": sentiment_label,
                    "sentiment_score": sentiment_score,

                    # liked_count = engagement weight
                    # Phase 3 uses: AVG(score) weighted by likes
                    "liked_count":     msg.get(
                                           "likes", {}
                                       ).get("total", 0),
                    "source":          "stocktwits",
                    "fetched_at":      datetime.now(
                                           timezone.utc
                                       ).isoformat()
                })

        except httpx.TimeoutException:
            logger.warning(
                "stocktwits_timeout",
                extra={"symbol": symbol}
            )
        except Exception as e:
            logger.error(
                "stocktwits_fetch_error",
                extra={"symbol": symbol, "error": str(e)}
            )

        return messages

    def fetch_and_publish(self) -> int:
        """
        Main method — called by Celery every hour.

        Complete flow:
        ┌──────────────────────────────────────────────────┐
        │ 1. get_active_symbols()                          │
        │    → RDS stocks table (Phase 1)                  │
        │    → ["AAPL", "MSFT", ...]                       │
        │                                                  │
        │ 2. fetch_symbol_messages() per symbol            │
        │    → Stocktwits API (free, no key)               │
        │    → converts Bullish→+1.0, Bearish→-1.0        │
        │                                                  │
        │ 3. s3_helper.save_raw_data()                     │
        │    → S3 sentiment/date/batch.json                │
        │    → permanent archive                           │
        │                                                  │
        │ 4. producer.produce() per post                   │
        │    → Kafka "sentiment.raw" topic                 │
        │    → sentiment_consumer.py picks up              │
        │    → saves to RDS stocktwits_posts              │
        └──────────────────────────────────────────────────┘

        Returns: count of posts published to Kafka
        """
        symbols = self.get_active_symbols()

        if not symbols:
            logger.warning("no_active_symbols_for_stocktwits")
            return 0

        all_messages = []

        # ── Fetch per symbol ──────────────────────────────
        #
        # 10 symbols × 30 messages = ~300 posts per run.
        # Each request is fast — Stocktwits is low-latency.
        for symbol in symbols:
            messages = self.fetch_symbol_messages(symbol)
            all_messages.extend(messages)
            logger.info(
                "stocktwits_fetched",
                extra={
                    "symbol": symbol,
                    "count": len(messages)
                }
            )

        if not all_messages:
            logger.warning("no_stocktwits_messages")
            return 0

        # ── Archive to S3 ─────────────────────────────────
        #
        # s3_helper from Day 1 — zero changes needed.
        # Path: sentiment/2024-01-15/batch_093000.json
        #
        # S3 = permanent archive (months/years)
        # Kafka = temporary queue (expires after 7 days)
        # Always archive to S3 before Kafka.
        try:
            s3_helper.save_raw_data(
                data=all_messages,
                data_type="sentiment",
                identifier="batch"
            )
        except Exception as e:
            logger.error(f"s3_sentiment_save_failed: {e}")

        # ── Publish to Kafka ──────────────────────────────
        #
        # Topic: "sentiment.raw"
        # Key: ticker symbol
        # Value: post data as JSON bytes
        #
        # Keying by symbol means all AAPL posts
        # go to the same Kafka partition → processed in order
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
        """Close HTTP client when object is destroyed."""
        self.http_client.close()


# Single instance — reused by Celery tasks
stocktwits_fetcher = StocktwitsFetcher()