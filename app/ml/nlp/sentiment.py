# =========================================================
# NEWS SENTIMENT SCORING
# =========================================================
#
# What does this file do in plain English?
#
# Phase 2 stored news articles with sentiment_score = NULL.
# This file reads those unscored articles and fills in
# a sentiment score from -1.0 (very negative) to +1.0
# (very positive) using a pre-trained ML model.
#
# We use sentence-transformers — a model that understands
# the MEANING of text, not just keywords.
#
# Difference from Phase 2's keyword scorer:
# Phase 2: "beats" = bullish, "drops" = bearish
#          Simple, fast, often wrong
#          "Apple beats cancer diagnosis" → wrongly bullish
#
# Phase 3: understands context and meaning
#          "Apple beats earnings estimates" → bullish
#          "Apple beats cancer diagnosis" → neutral (health news)
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# RDS news_articles table
#       ↓ articles where sentiment_score = NULL
#       ↓ read by this pipeline
# sentence-transformers model (all-MiniLM-L6-v2)
#       ↓ encodes text into 384-dim vector
#       ↓ compares to "positive news" and "negative news"
#       ↓ produces score -1.0 to +1.0
# RDS news_articles.sentiment_score ← filled
# RDS news_articles.sentiment_label ← filled
#       ↓ read by
# api/news.py → GET /api/news/AAPL/sentiment
# Phase 3 anomaly detector (combines price + sentiment)
# Phase 4 RAG agent (searches sentiment context)
# ─────────────────────────────────────────────────────────

import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.news import NewsArticle
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Reference sentences for sentiment comparison ──────────
#
# How zero-shot sentiment scoring works:
# 1. Encode the article headline into a 384-dim vector
# 2. Encode "positive financial news" into a vector
# 3. Encode "negative financial news" into a vector
# 4. Measure cosine similarity to each reference
# 5. Score = similarity_to_positive - similarity_to_negative
#
# This is zero-shot — we never trained on financial news.
# The model understands meaning from pre-training.
POSITIVE_REFERENCE = (
    "positive financial news stock price increase "
    "earnings beat profit growth bullish market rally"
)

NEGATIVE_REFERENCE = (
    "negative financial news stock price decrease "
    "earnings miss loss decline bearish market crash"
)

# Load model once at module level
# all-MiniLM-L6-v2: fast, accurate, 22MB model
# Downloads automatically on first use
try:
    model = SentenceTransformer("all-MiniLM-L6-v2")
    logger.info("sentiment_model_loaded")
except Exception as e:
    model = None
    logger.error(
        "sentiment_model_load_error",
        extra={"error": str(e)}
    )

# Pre-encode reference sentences once
# No need to re-encode on every article
if model:
    POS_EMBEDDING = model.encode(
        POSITIVE_REFERENCE,
        normalize_embeddings=True
    )
    NEG_EMBEDDING = model.encode(
        NEGATIVE_REFERENCE,
        normalize_embeddings=True
    )


def score_text(text: str) -> tuple[float, str]:
    """
    Scores a text string for financial sentiment.

    Returns (score, label):
    score:  -1.0 to +1.0
    label:  "positive" / "negative" / "neutral"

    How cosine similarity works:
    Two vectors pointing in the same direction → score = 1.0
    Two vectors perpendicular               → score = 0.0
    Two vectors pointing opposite           → score = -1.0

    We compare the article vector to positive/negative
    reference vectors and take the difference.
    """
    if not model or not text:
        return 0.0, "neutral"

    try:
        # ── Encode the article text ───────────────────────
        #
        # normalize_embeddings=True → unit vectors (length=1)
        # This makes cosine similarity = dot product
        # which is faster to compute
        article_embedding = model.encode(
            text[:512],  # limit tokens for speed
            normalize_embeddings=True
        )

        # ── Calculate cosine similarity ───────────────────
        #
        # np.dot() of two normalised vectors = cosine similarity
        # Range: -1.0 to +1.0
        pos_similarity = float(
            np.dot(article_embedding, POS_EMBEDDING)
        )
        neg_similarity = float(
            np.dot(article_embedding, NEG_EMBEDDING)
        )

        # ── Compute final score ───────────────────────────
        #
        # score > 0 = more similar to positive reference
        # score < 0 = more similar to negative reference
        # Raw score is small (0.1 to 0.4 range typically)
        # We multiply by 5 to spread it out more
        raw_score = pos_similarity - neg_similarity
        score     = round(float(np.clip(raw_score * 5, -1.0, 1.0)), 4)

        # ── Determine label ───────────────────────────────
        if score > 0.1:
            label = "positive"
        elif score < -0.1:
            label = "negative"
        else:
            label = "neutral"

        return score, label

    except Exception as e:
        logger.error(
            "sentiment_score_error",
            extra={"error": str(e)}
        )
        return 0.0, "neutral"


def run_sentiment_scoring(batch_size: int = 100) -> dict:
    """
    Scores unscored news articles in RDS.

    Flow:
    ┌──────────────────────────────────────────────────┐
    │ 1. Query RDS for articles with NULL score        │
    │ 2. Score each headline + body snippet            │
    │ 3. Update sentiment_score + sentiment_label      │
    └──────────────────────────────────────────────────┘

    Called by Celery every 30 minutes.
    Each run processes up to batch_size articles.
    Over time all articles get scored.
    """
    if not model:
        return {"status": "error", "reason": "model not loaded"}

    db: Session = SessionLocal()
    scored = 0

    try:
        # ── Get unscored articles ─────────────────────────
        #
        # Filter: sentiment_score IS NULL
        # These are articles Phase 2 ingested but never scored
        articles = db.query(NewsArticle).filter(
            NewsArticle.sentiment_score == None
        ).limit(batch_size).all()

        if not articles:
            logger.info("no_unscored_articles")
            return {"status": "no_articles", "scored": 0}

        for article in articles:
            # ── Build text to score ───────────────────────
            #
            # Use headline + first 200 chars of body
            # Headline is most important for sentiment
            # Body adds context
            text = article.headline
            if article.body:
                text += f" {article.body[:200]}"

            # ── Score it ──────────────────────────────────
            score, label = score_text(text)

            article.sentiment_score = score
            article.sentiment_label = label
            scored += 1

        db.commit()

        logger.info(
            "sentiment_scoring_completed",
            extra={"scored": scored}
        )

        return {"status": "success", "scored": scored}

    except Exception as e:
        db.rollback()
        logger.error(
            "sentiment_scoring_error",
            extra={"error": str(e)}
        )
        return {"status": "error", "error": str(e)}

    finally:
        db.close()