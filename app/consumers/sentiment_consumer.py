# path: app/consumers/sentiment_consumer.py

# =========================================================
# SENTIMENT CONSUMER — Kafka → RDS
# =========================================================
#
# What does this file do in plain English?
#
# Identical pattern to news_consumer.py but handles
# the "sentiment.raw" Kafka topic instead of "news.raw".
#
# Listens for Stocktwits messages published by
# stocktwits_fetcher.py and saves them to the
# RDS stocktwits_posts table.
#
# Key difference from NewsConsumer:
# NewsConsumer  → saves articles WITHOUT sentiment score
#                 (Phase 3 fills it later)
# SentimentConsumer → saves posts WITH sentiment score
#                     (Stocktwits pre-labelled it already)
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO EVERYTHING ELSE:
#
# Kafka "sentiment.raw" topic
#       ↓ messages published by stocktwits_fetcher.py
#         (with sentiment_score already filled as +1/-1/0)
# THIS FILE (sentiment_consumer.py)
#       ↓ opens DB session via
# session.py → SessionLocal() ─────── (Phase 1)
#       ↓ deduplicates by stocktwits_id using
# StocktwitsPost model ───────────── (model above)
#       ↓ inserts new posts to
# RDS stocktwits_posts table
#       ↓ later read by
# Phase 3 ──
#   RDS stocktwits_posts ──┐
#                           ├──→ sentiment_aggregator.py
#   RDS news_articles ─────┘    → AVG(sentiment_score)
#                                  per ticker per day
#                                → ClickHouse daily_sentiment
# Phase 4 ──
#   body text → pgvector embeddings
#   searched by AI agent
# ─────────────────────────────────────────────────────────

import json
import threading
from confluent_kafka import Consumer, KafkaError
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.stocktwits_post import StocktwitsPost
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SentimentConsumer:
    """
    Listens to Kafka "sentiment.raw" and writes to RDS.

    In plain English: the filing clerk for sentiment data.
    Same job as NewsConsumer but for Stocktwits posts.

    Connects to:
    ┌──────────────────────────────────────────────────┐
    │ Kafka Consumer     → reads sentiment.raw topic   │
    │ session.py         → DB sessions per message     │
    │ StocktwitsPost     → model for RDS insertion     │
    └──────────────────────────────────────────────────┘
    """

    def __init__(self):

        # ── Kafka Consumer ────────────────────────────────
        #
        # Different group.id from news-consumer-group.
        # Each consumer group tracks its own position
        # in Kafka independently.
        # "sentiment-consumer-group" tracks position
        # in "sentiment.raw" separately from
        # "news-consumer-group" tracking "news.raw".
        self.consumer = Consumer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": "sentiment-consumer-group",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False
        })

        self.consumer.subscribe(["sentiment.raw"])
        self.running = False

    def save_post(
        self,
        post_data: dict,
        db
    ) -> bool:
        """
        Saves one Stocktwits post to RDS.

        Deduplication by stocktwits_id.
        Same logic as save_article() in NewsConsumer
        but for StocktwitsPost model and stocktwits_id field.

        Key difference from NewsConsumer.save_article():
        ┌────────────────────────────────────────────────┐
        │ NewsConsumer saves:                            │
        │   sentiment_score = NULL (Phase 3 fills later) │
        │                                                │
        │ SentimentConsumer saves:                       │
        │   sentiment_score = already +1.0/-1.0/0.0      │
        │   (stocktwits_fetcher.py converted it)        │
        └────────────────────────────────────────────────┘
        """
        stocktwits_id = post_data.get("stocktwits_id", "")

        if not stocktwits_id:
            return False

        try:
            # ── Check for duplicate ───────────────────────
            existing = db.query(StocktwitsPost).filter(
                StocktwitsPost.stocktwits_id == stocktwits_id
            ).first()

            if existing:
                return False

            # ── Create new StocktwitsPost object ──────────
            #
            # sentiment_score is ALREADY filled here.
            # stocktwits_fetcher converted "Bullish" → +1.0
            # Phase 3 does NOT need to score these —
            # just aggregate: AVG(sentiment_score) per ticker
            post = StocktwitsPost(
                stocktwits_id=stocktwits_id,
                body=post_data.get("body"),
                ticker_symbol=post_data.get("ticker_symbol", ""),
                author=post_data.get("author"),
                posted_at=post_data.get("posted_at"),
                sentiment_label=post_data.get("sentiment_label"),
                sentiment_score=post_data.get("sentiment_score", 0.0),
                liked_count=post_data.get("liked_count", 0)
            )

            db.add(post)
            db.commit()
            return True

        except IntegrityError:
            db.rollback()
            return False

        except Exception as e:
            db.rollback()
            logger.error(
                "sentiment_save_error",
                extra={
                    "stocktwits_id": stocktwits_id,
                    "error": str(e)
                }
            )
            return False

    def start(self) -> None:
        """
        Starts consuming in a background thread.
        Identical pattern to NewsConsumer.start().
        """
        self.running = True

        def consume_loop():
            logger.info("sentiment_consumer_started")

            while self.running:
                msg = self.consumer.poll(1.0)

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error(
                            f"kafka_error: {msg.error()}"
                        )
                        continue

                db = SessionLocal()

                try:
                    data = json.loads(
                        msg.value().decode("utf-8")
                    )
                    saved = self.save_post(data, db)

                    if saved:
                        logger.info(
                            "sentiment_post_saved",
                            extra={
                                "ticker": data.get("ticker_symbol"),
                                "sentiment": data.get("sentiment_label"),
                                "score": data.get("sentiment_score")
                            }
                        )

                    self.consumer.commit()

                except Exception as e:
                    logger.error(
                        "sentiment_consumer_error",
                        extra={"error": str(e)}
                    )
                finally:
                    db.close()

        thread = threading.Thread(
            target=consume_loop,
            daemon=True
        )
        thread.start()

    def stop(self) -> None:
        self.running = False
        self.consumer.close()


# Single instance — started in main.py lifespan
sentiment_consumer = SentimentConsumer()