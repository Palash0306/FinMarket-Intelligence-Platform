# path: app/rag/vector_store.py

# =========================================================
# VECTOR STORE — Semantic Search on News Articles
# =========================================================
#
# What does this file do in plain English?
#
# Phase 3 stored 384-dimensional vectors for each news
# article in the pgvector column. This file provides
# the search interface — given a question, find the
# most relevant articles by meaning, not keyword.
#
# How semantic search works:
# 1. Convert the user's question to a 384-dim vector
# 2. Compare that vector to all article vectors
#    using cosine similarity
# 3. Return the articles with highest similarity scores
#
# Example:
# Question: "How did Apple perform in earnings?"
# → encoded as vector [0.12, -0.45, 0.33, ...]
# → compared to all news article vectors
# → "Apple Q3 earnings beat estimates" scores 0.89
# → "Apple launches new MacBook" scores 0.61
# → "Goldman Sachs quarterly results" scores 0.12
# → returns top 5 most relevant articles
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# Phase 3 embed_news.py
#       ↓ stored 384-dim vectors in
# RDS news_articles.embedding (pgvector)
#       ↓ THIS FILE searches those vectors
# rag_tools.py imports search_similar_articles()
#       ↓ called by LangGraph agent nodes
# agent.py uses results as LLM context
# ─────────────────────────────────────────────────────────

import numpy as np
from sqlalchemy import text
from sentence_transformers import SentenceTransformer

from app.db.session import SessionLocal, engine
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Reuse same model as Phase 3 ───────────────────────────
#
# sentence-transformers caches the model after first download.
# Loading the same model name reuses the cached version.
# Must use the SAME model that created the embeddings
# (all-MiniLM-L6-v2 produces 384-dim vectors).
# Using a different model would give incomparable vectors.
try:
    embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    logger.info("vector_store_model_loaded")
except Exception as e:
    embed_model = None
    logger.error(f"vector_store_model_error: {e}")


def embed_query(query: str) -> list[float]:
    """
    Converts a user question to a 384-dim vector.

    Same process as Phase 3 embed_news.py but for queries.
    The key insight: if the model encodes articles and queries
    the same way, similar meanings produce similar vectors.

    Connection:
    User question text
        ↓ this function
        ↓ same model used in Phase 3
    384-dim vector
        ↓ used by search_similar_articles()
    """
    if not embed_model:
        return []

    vector = embed_model.encode(
        query,
        normalize_embeddings=True
    )
    return vector.tolist()


def search_similar_articles(
    query: str,
    symbol: str = None,
    limit: int = 5,
    min_similarity: float = 0.3
) -> list[dict]:
    """
    Finds news articles most semantically similar to query.

    Uses pgvector's cosine distance operator (<=>)
    to find closest vectors to the query vector.

    Args:
        query:          user's question or search text
        symbol:         optional filter by ticker (AAPL etc.)
        limit:          max articles to return
        min_similarity: minimum similarity score (0-1)
                        filters out irrelevant articles

    Returns list of article dicts with similarity scores.

    Connection:
    embed_query() converts question to vector
        ↓
    pgvector cosine similarity search on RDS
        ↓
    returns top N most relevant articles
        ↓
    rag_tools.py uses these as LLM context
    """
    if not embed_model:
        return []

    # ── Convert query to vector ───────────────────────────
    query_vector = embed_query(query)

    if not query_vector:
        return []

    try:
        with engine.connect() as conn:

            # ── Build SQL query ───────────────────────────
            #
            # pgvector's <=> operator = cosine distance
            # cosine distance = 1 - cosine_similarity
            # So lower distance = more similar
            # We convert: similarity = 1 - distance
            #
            # The ::vector cast tells Postgres this is
            # a pgvector type, not a plain array
            if symbol:
                sql = text("""
                    SELECT
                        id,
                        headline,
                        body,
                        source,
                        published_at,
                        ticker_symbols,
                        sentiment_score,
                        sentiment_label,
                        1 - (embedding <=> :query_vec::vector) AS similarity
                    FROM news_articles
                    WHERE embedding IS NOT NULL
                      AND ticker_symbols ILIKE :symbol
                    ORDER BY embedding <=> :query_vec::vector
                    LIMIT :limit
                """)
                result = conn.execute(sql, {
                    "query_vec": str(query_vector),
                    "symbol":    f"%{symbol}%",
                    "limit":     limit
                })
            else:
                sql = text("""
                    SELECT
                        id,
                        headline,
                        body,
                        source,
                        published_at,
                        ticker_symbols,
                        sentiment_score,
                        sentiment_label,
                        1 - (embedding <=> :query_vec::vector) AS similarity
                    FROM news_articles
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> :query_vec::vector
                    LIMIT :limit
                """)
                result = conn.execute(sql, {
                    "query_vec": str(query_vector),
                    "limit":     limit
                })

            # ── Convert rows to dicts ─────────────────────
            articles = []
            for row in result:
                similarity = float(row[8])

                # Filter out articles below similarity threshold
                if similarity < min_similarity:
                    continue

                articles.append({
                    "id":              row[0],
                    "headline":        row[1],
                    "body":            (row[2] or "")[:500],
                    "source":          row[3],
                    "published_at":    row[4],
                    "ticker_symbols":  row[5],
                    "sentiment_score": row[6],
                    "sentiment_label": row[7],
                    "similarity":      round(similarity, 4)
                })

            logger.info(
                "vector_search_completed",
                extra={
                    "query":   query[:50],
                    "results": len(articles)
                }
            )

            return articles

    except Exception as e:
        logger.error(
            "vector_search_error",
            extra={"error": str(e)}
        )
        return []