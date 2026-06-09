# =========================================================
# PGVECTOR EMBEDDINGS
# =========================================================
#
# What does this file do in plain English?
#
# It converts news article text into vectors (lists of numbers)
# and stores them in Postgres using pgvector extension.
#
# Why vectors? Because they enable SEMANTIC SEARCH.
#
# Normal search: "Apple earnings" finds articles containing
#                those exact words. Misses "AAPL profit report".
#
# Vector search: "Apple earnings" finds articles that are
#                SEMANTICALLY SIMILAR — even if they use
#                different words. Finds "AAPL quarterly profit"
#                because the meaning is similar.
#
# Phase 4 RAG uses these vectors to find relevant articles
# when the AI agent answers questions like:
# "What's the latest news about Apple's revenue growth?"
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# RDS news_articles table
#       ↓ articles where is_embedded = False
#       ↓ read by this pipeline
# sentence-transformers model
#       ↓ converts text → 384-dim vector
# RDS news_articles.embedding column (pgvector)
#       ↓ set is_embedded = True
#       ↓ read by
# Phase 4 RAG pipeline
#   → semantic search: "find articles similar to this query"
#   → used by LangGraph AI agent to answer questions
# ─────────────────────────────────────────────────────────

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session
from sentence_transformers import SentenceTransformer

from app.db.session import SessionLocal, engine
from app.models.news import NewsArticle
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Embedding dimensions ──────────────────────────────────
#
# all-MiniLM-L6-v2 produces 384-dimensional vectors.
# Each dimension captures some aspect of meaning.
# 384 floats = ~1.5KB per article — very compact.
EMBEDDING_DIM = 384

# Reuse the same model as sentiment.py
# sentence-transformers caches the model automatically
try:
    embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    logger.info("embedding_model_loaded")
except Exception as e:
    embed_model = None
    logger.error(
        "embedding_model_error",
        extra={"error": str(e)}
    )


def ensure_embedding_column() -> None:
    """
    Adds embedding column to news_articles if it doesn't exist.

    Uses pgvector's VECTOR type which stores float arrays
    and supports fast similarity search with special indexes.

    This runs once at startup — safe to call multiple times
    because of the IF NOT EXISTS check.

    Connection chain:
    session.py engine → raw SQL → Postgres pgvector extension
    """
    try:
        with engine.connect() as conn:
            # ── Enable pgvector extension ─────────────────
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

            # ── Add embedding column ──────────────────────
            #
            # VECTOR(384) = array of 384 floats
            # This is pgvector's special column type
            conn.execute(text(f"""
                ALTER TABLE news_articles
                ADD COLUMN IF NOT EXISTS
                embedding VECTOR({EMBEDDING_DIM})
            """))

            # ── Create vector similarity index ────────────
            #
            # ivfflat = Inverted File Flat index
            # Enables fast approximate nearest-neighbour search
            # lists=100 = 100 clusters (good for ~100k rows)
            # vector_cosine_ops = use cosine similarity
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS
                news_embedding_idx
                ON news_articles
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """))

            conn.commit()
            logger.info("embedding_column_ready")

    except Exception as e:
        logger.warning(
            "embedding_column_setup_error",
            extra={"error": str(e)}
        )


def embed_text(text_input: str) -> list[float]:
    """
    Converts text to a 384-dimensional embedding vector.

    The vector captures the MEANING of the text.
    Similar texts produce similar vectors.
    Different texts produce different vectors.

    Returns list of 384 floats.
    """
    if not embed_model:
        return []

    embedding = embed_model.encode(
        text_input[:512],  # truncate for speed
        normalize_embeddings=True  # unit vectors for cosine similarity
    )

    return embedding.tolist()


def run_embedding_pipeline(batch_size: int = 50) -> dict:
    """
    Embeds unembedded news articles into pgvector.

    Flow:
    ┌──────────────────────────────────────────────────┐
    │ 1. Query RDS for articles where is_embedded=False│
    │ 2. Encode headline + body into 384-dim vector    │
    │ 3. Store vector in embedding column (pgvector)   │
    │ 4. Set is_embedded = True                        │
    └──────────────────────────────────────────────────┘

    Called by Celery every hour.
    Each run embeds up to batch_size articles.
    """
    if not embed_model:
        return {"status": "error", "reason": "model not loaded"}

    # ── Ensure pgvector column exists ────────────────────
    ensure_embedding_column()

    db: Session = SessionLocal()
    embedded = 0

    try:
        # ── Get unembedded articles ───────────────────────
        articles = db.query(NewsArticle).filter(
            NewsArticle.is_embedded == False
        ).limit(batch_size).all()

        if not articles:
            return {"status": "no_articles", "embedded": 0}

        for article in articles:
            # ── Build text to embed ───────────────────────
            text_to_embed = article.headline
            if article.body:
                text_to_embed += f" {article.body[:300]}"

            # ── Get embedding vector ──────────────────────
            embedding = embed_text(text_to_embed)

            if not embedding:
                continue

            # ── Store in pgvector column ──────────────────
            #
            # pgvector stores vectors as PostgreSQL arrays.
            # We use raw SQL here because SQLAlchemy doesn't
            # natively support pgvector types yet.
            db.execute(
                text("""
                    UPDATE news_articles
                    SET embedding = :embedding,
                        is_embedded = true
                    WHERE id = :article_id
                """),
                {
                    "embedding":  str(embedding),
                    "article_id": article.id
                }
            )

            embedded += 1

        db.commit()

        logger.info(
            "embedding_pipeline_completed",
            extra={"embedded": embedded}
        )

        return {"status": "success", "embedded": embedded}

    except Exception as e:
        db.rollback()
        logger.error(
            "embedding_error",
            extra={"error": str(e)}
        )
        return {"status": "error", "error": str(e)}

    finally:
        db.close()