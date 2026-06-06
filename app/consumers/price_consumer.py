# path: app/consumers/price_consumer.py

# =========================================================
# PRICE CONSUMER — Kafka → ClickHouse
# =========================================================
#
# What does this do in plain English?
#
# The fetcher drops price messages in Kafka.
# This consumer sits there listening.
# The moment a message arrives, it reads it and
# writes the price data into ClickHouse.
#
# Think of it as:
# Fetcher = person dropping letters in a postbox
# Kafka   = the postbox
# Consumer = the postman who empties the box
#            and delivers to ClickHouse
#
# Why not write directly to ClickHouse from the fetcher?
# Decoupling. If ClickHouse is temporarily slow or down,
# messages queue up in Kafka and get processed when
# ClickHouse recovers. Nothing is lost.

import json
import threading
from datetime import datetime, timezone
from confluent_kafka import Consumer, KafkaError
from app.db.clickhouse import get_clickhouse_client
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PriceConsumer:
    """
    Listens to Kafka "market.prices" topic and writes
    price data to ClickHouse.
    """

    def __init__(self):
        # ── Kafka Consumer ────────────────────────────────
        #
        # Consumer = the receiving side of Kafka
        # group.id: consumers with same ID share the load
        # auto.offset.reset: "earliest" = process all
        #   unprocessed messages when starting fresh
        self.consumer = Consumer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": "price-consumer-group",
            "auto.offset.reset": "earliest",
            # Commit offsets manually — we confirm processing
            # only after successfully writing to ClickHouse
            "enable.auto.commit": False
        })

        # Subscribe to the prices topic
        self.consumer.subscribe(["market.prices"])
        self.running = False

    def process_message(self, price_data: dict) -> None:
        """
        Writes one price record to ClickHouse.

        Fix: timestamp comes from Kafka as an ISO string.
        ClickHouse driver needs a Python datetime object.
        We convert it here before inserting.

        Connects to:
        Kafka "market.prices" → this method → ClickHouse ohlcv
        """
        client = get_clickhouse_client()

        # ── Convert timestamp string → datetime object ────────
        #
        # stock_fetcher.py stores timestamp as ISO string:
        # "2026-06-04T08:45:07.729779+00:00"
        #
        # ClickHouse driver needs a Python datetime object.
        # fromisoformat() parses the ISO string back to datetime.
        raw_ts = price_data["timestamp"]

        if isinstance(raw_ts, str):
            # Parse ISO format string to datetime
            timestamp = datetime.fromisoformat(raw_ts)
        else:
            # Already a datetime — use as is
            timestamp = raw_ts

        # Make sure it has timezone info
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        # ── Insert into ClickHouse ────────────────────────────
        client.execute(
            """
            INSERT INTO ohlcv
            (symbol, timestamp, open, high, low, close, volume, source)
            VALUES
            """,
            [(
                price_data["symbol"],
                timestamp,              # ← now a proper datetime
                float(price_data["open"]),
                float(price_data["high"]),
                float(price_data["low"]),
                float(price_data["close"]),
                float(price_data["volume"]),
                price_data.get("source", "yfinance")
            )]
        )

        logger.info(
            "price_stored",
            extra={
                "symbol": price_data["symbol"],
                "close":  price_data["close"]
            }
        )

    def start(self) -> None:
        """
        Starts consuming messages in a background thread.

        threading.Thread means the consumer runs in the
        background without blocking the main app.

        Think of it as: hiring a full-time postman who
        keeps checking the postbox all day, every day,
        without stopping anything else from running.
        """
        self.running = True

        def consume_loop():
            logger.info("price_consumer_started")

            while self.running:
                # poll(1.0) waits up to 1 second for a message
                # Returns None if no message in that time
                msg = self.consumer.poll(1.0)

                if msg is None:
                    continue

                # ── Handle errors ─────────────────────────
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        # Normal — reached end of partition
                        continue
                    else:
                        logger.error(f"kafka_error: {msg.error()}")
                        continue

                try:
                    # ── Decode the message ────────────────
                    #
                    # msg.value() returns bytes
                    # .decode("utf-8") converts to string
                    # json.loads() converts string to dict
                    price_data = json.loads(
                        msg.value().decode("utf-8")
                    )

                    # ── Process it ────────────────────────
                    self.process_message(price_data)

                    # ── Commit offset ─────────────────────
                    #
                    # Tells Kafka "I've processed this message"
                    # So if consumer restarts, it picks up
                    # from where it left off — not from scratch
                    self.consumer.commit()

                except Exception as e:
                    logger.error(
                        "price_consumer_error",
                        extra={"error": str(e)}
                    )

        # Start in background thread
        thread = threading.Thread(
            target=consume_loop,
            daemon=True  # stops automatically when app stops
        )
        thread.start()

    def stop(self) -> None:
        self.running = False
        self.consumer.close()


# Single instance
price_consumer = PriceConsumer()