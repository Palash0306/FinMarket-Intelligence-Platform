# path: app/consumers/news_consumer.py

# =========================================================
# NEWS CONSUMER — Kafka → RDS
# =========================================================
#
# What does this file do in plain English?
#
# This listens to Kafka "news.raw" topic continuously.
# The moment news_fetcher.py drops a message there,
# this consumer picks it up within 1 second and saves
# it to the RDS news_articles table.
#
# It handles two things:
# 1. Deduplication — checks URL before inserting
#    "Has this article been saved before? If yes → skip."
# 2. Error isolation — each message is its own transaction
#    "If saving one article fails → skip it, don't crash."
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO EVERYTHING ELSE:
#
# Kafka "news.raw" topic
#       ↓ messages published by news_fetcher.py
# THIS FILE (news_consumer.py)
#       ↓ opens fresh DB session for each message via
# session.py → SessionLocal() ──── (Phase 1)
#       ↓ checks for duplicates using
# NewsArticle model → url field ──── (model above)
#       ↓ inserts new articles using
# NewsArticle model → db.add() + db.commit()
#       ↓ writes to
# RDS news_articles table
#       ↓ later read by
# Phase 3 ── sentiment_score column gets filled
# Phase 4 ── is_embedded column gets filled
#             body text → pgvector embeddings
# ─────────────────────────────────────────────────────────

import json
import threading
from confluent_kafka import Consumer, KafkaError
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.news import NewsArticle
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class NewsConsumer:
    """
    Listens to Kafka "news.raw" and writes to RDS.

    In plain English: the filing clerk for news.
    Sits at the Kafka postbox all day, picks up
    every envelope (message), checks it's not a
    duplicate, and files it in the RDS library.

    Connects to:
    ┌──────────────────────────────────────────────────┐
    │ Kafka Consumer  → reads from news.raw topic      │
    │ session.py      → DB sessions per message        │
    │ NewsArticle     → model for RDS insertion        │
    └──────────────────────────────────────────────────┘
    """

    def __init__(self):

        # ── Kafka Consumer ────────────────────────────────
        #
        # Consumer = receiving side of Kafka
        # (Producer in fetcher = sending side)
        #
        # group.id: consumers with same group.id share work
        # If you ran 2 consumers with same group, Kafka
        # would split the messages between them (load balance)
        #
        # auto.offset.reset = "earliest":
        # When starting fresh, process ALL unread messages.
        # This means if consumer was down for 2 hours,
        # it catches up on all messages it missed.
        #
        # enable.auto.commit = False:
        # We manually tell Kafka "I processed this message"
        # only AFTER successfully saving to RDS.
        # If saving fails, the message stays in Kafka for retry.
        self.consumer = Consumer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": "news-consumer-group",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False
        })

        # Subscribe to the news topic
        # (sentiment_consumer subscribes to sentiment.raw)
        self.consumer.subscribe(["news.raw"])
        self.running = False

    def save_article(
        self,
        article_data: dict,
        db
    ) -> bool:
        """
        Saves one news article to RDS news_articles table.

        Returns True if saved, False if duplicate/skipped.

        Deduplication logic:
        ┌────────────────────────────────────────────────┐
        │ Check: does URL already exist in RDS?          │
        │ Yes → return False (skip silently)             │
        │ No  → insert new row → return True             │
        └────────────────────────────────────────────────┘

        Why deduplicate?
        NewsAPI and RSS might both return the same article.
        (Reuters article appears in both sources.)
        Without deduplication: thousands of duplicate rows.
        With deduplication: clean, unique articles only.
        """
        url = article_data.get("url", "")

        # Skip articles with no URL or no headline
        # (can't deduplicate without URL)
        if not url or not article_data.get("headline"):
            return False

        try:
            # ── Check for existing article ────────────────
            #
            # db.query(NewsArticle).filter(...).first()
            # translates to SQL:
            # SELECT * FROM news_articles WHERE url = ? LIMIT 1
            existing = db.query(NewsArticle).filter(
                NewsArticle.url == url
            ).first()

            if existing:
                # Already in RDS — skip silently
                return False

            # ── Create new NewsArticle object ─────────────
            #
            # Same pattern as seed_stocks.py (Phase 1):
            # Create Python object → db.add() → db.commit()
            #
            # NOTE: sentiment_score = NULL at this stage
            #       Phase 3 fills it later
            # NOTE: is_embedded = False at this stage
            #       Phase 4 sets it True after embedding
            article = NewsArticle(
                url=url,
                headline=article_data.get("headline", "")[:1024],
                body=article_data.get("body"),
                source=article_data.get("source", "unknown"),
                author=article_data.get("author"),
                published_at=article_data.get("published_at"),
                ticker_symbols=article_data.get("ticker_symbols")
            )

            db.add(article)
            db.commit()
            return True

        except IntegrityError:
            # IntegrityError = unique constraint violated
            # Race condition: two workers tried to insert
            # the same URL at exactly the same time.
            # Roll back and skip — no harm done.
            db.rollback()
            return False

        except Exception as e:
            db.rollback()
            logger.error(
                "news_save_error",
                extra={"url": url, "error": str(e)}
            )
            return False

    def start(self) -> None:
        """
        Starts consuming messages in a background thread.

        Background thread = runs alongside the FastAPI app
        without blocking it.

        Think of it as: hiring a full-time postman who
        checks the Kafka postbox every second all day
        while the API keeps serving web requests normally.

        Pattern:
        ┌────────────────────────────────────────────────┐
        │ threading.Thread(target=consume_loop)          │
        │ → runs consume_loop() in background            │
        │ → daemon=True means it stops when app stops    │
        └────────────────────────────────────────────────┘
        """
        self.running = True

        def consume_loop():
            logger.info("news_consumer_started")

            while self.running:

                # ── Poll for next message ─────────────────
                #
                # poll(1.0) = wait up to 1 second for a message
                # Returns None if no message arrived in 1 second
                # Returns message object if one arrived
                msg = self.consumer.poll(1.0)

                if msg is None:
                    # No message yet — keep waiting
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        # Normal — reached end of current messages
                        # Will get new ones as fetcher publishes
                        continue
                    else:
                        logger.error(
                            f"kafka_consumer_error: {msg.error()}"
                        )
                        continue

                # ── Open fresh DB session per message ─────
                #
                # Why new session per message (not one shared)?
                # If saving article #5 fails and we rollback,
                # only article #5 is affected.
                # Articles #1-4 are already committed safely.
                # One shared session = one failure rolls back ALL.
                db = SessionLocal()

                try:
                    # ── Decode message ────────────────────
                    #
                    # msg.value() = bytes from Kafka
                    # .decode("utf-8") = convert bytes to string
                    # json.loads() = convert string to dict
                    article_data = json.loads(
                        msg.value().decode("utf-8")
                    )

                    saved = self.save_article(article_data, db)

                    if saved:
                        logger.info(
                            "news_article_saved",
                            extra={
                                "source": article_data.get("source"),
                                "ticker": article_data.get("ticker_symbols")
                            }
                        )

                    # ── Confirm processing to Kafka ───────
                    #
                    # commit() tells Kafka:
                    # "I've processed this message successfully"
                    # If consumer restarts, it picks up from
                    # AFTER this message — not from the start.
                    self.consumer.commit()

                except Exception as e:
                    logger.error(
                        "news_consumer_loop_error",
                        extra={"error": str(e)}
                    )
                finally:
                    # Always close the DB session
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
news_consumer = NewsConsumer()