# =========================================================
# SPACY NER PIPELINE
# =========================================================
#
# What is NER in plain English?
#
# NER = Named Entity Recognition.
# It reads text and identifies real-world things:
# people, organisations, locations, companies.
#
# Example:
# Text: "Apple reported record earnings beating Microsoft"
# NER finds: Apple (ORG), Microsoft (ORG)
# We then map "Apple" → "AAPL", "Microsoft" → "MSFT"
#
# Why do we need this?
# RSS feeds return general headlines without ticker symbols.
# A Reuters article says "Apple" not "$AAPL".
# NER + our company map fills in the ticker_symbols column
# in news_articles table that was left empty at ingestion.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# RDS news_articles table
#       ↓ articles where ticker_symbols = NULL
#       ↓ read by this pipeline
# spaCy en_core_web_sm model
#       ↓ finds ORG entities
#       ↓ maps company name → ticker symbol
# RDS news_articles.ticker_symbols
#       ↓ filled/enriched
# sentiment.py reads enriched articles next
# Phase 4 RAG can search by ticker
# ─────────────────────────────────────────────────────────

import spacy
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.news import NewsArticle
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Company name → ticker mapping ────────────────────────
#
# spaCy finds "Apple" in text, we map it to "AAPL".
# This covers our 10 tracked stocks plus common variants.
# Key = lowercase company name or common reference
# Value = ticker symbol
COMPANY_TICKER_MAP = {
    "apple":          "AAPL",
    "apple inc":      "AAPL",
    "microsoft":      "MSFT",
    "microsoft corp": "MSFT",
    "alphabet":       "GOOGL",
    "google":         "GOOGL",
    "nvidia":         "NVDA",
    "meta":           "META",
    "facebook":       "META",
    "meta platforms": "META",
    "jpmorgan":       "JPM",
    "jp morgan":      "JPM",
    "jpmorgan chase": "JPM",
    "goldman sachs":  "GS",
    "goldman":        "GS",
    "johnson":        "JNJ",
    "johnson & johnson": "JNJ",
    "exxon":          "XOM",
    "exxon mobil":    "XOM",
    "amazon":         "AMZN",
    "amazon.com":     "AMZN",
}

# Load spaCy model once at module level
# en_core_web_sm = small English model (~12MB)
# Loaded once to avoid reloading on every article
try:
    nlp = spacy.load("en_core_web_sm")
    logger.info("spacy_model_loaded")
except OSError:
    nlp = None
    logger.error(
        "spacy_model_not_found",
        extra={"fix": "run: python -m spacy download en_core_web_sm"}
    )


def extract_tickers_from_text(text: str) -> list[str]:
    """
    Extracts ticker symbols from text using spaCy NER.

    Process:
    1. spaCy reads the text and finds ORG entities
       (organisations/companies)
    2. We check each entity against COMPANY_TICKER_MAP
    3. Return list of matched ticker symbols

    Example:
    text = "Apple beats earnings, Microsoft disappoints"
    → spaCy finds: [Apple (ORG), Microsoft (ORG)]
    → mapped to: ["AAPL", "MSFT"]

    Also checks for raw ticker mentions like $AAPL or AAPL
    directly in the text as a fallback.
    """
    if not nlp or not text:
        return []

    found_tickers = set()

    # ── spaCy NER ─────────────────────────────────────────
    #
    # nlp(text) runs the full NLP pipeline:
    # tokenisation → POS tagging → NER
    # doc.ents = list of detected entities
    # Each entity has .text (the text) and .label_ (type)
    # We only care about ORG (organisation) entities
    doc = nlp(text[:5000])  # limit to 5000 chars for speed

    for ent in doc.ents:
        if ent.label_ in ("ORG", "PRODUCT"):
            entity_lower = ent.text.lower().strip()

            # Check exact match first
            if entity_lower in COMPANY_TICKER_MAP:
                found_tickers.add(
                    COMPANY_TICKER_MAP[entity_lower]
                )
                continue

            # Check partial match
            for company_name, ticker in COMPANY_TICKER_MAP.items():
                if company_name in entity_lower or \
                   entity_lower in company_name:
                    found_tickers.add(ticker)

    # ── Direct ticker mention fallback ────────────────────
    #
    # Some articles mention tickers directly: "$AAPL" or "AAPL"
    # We check for these even if NER missed the company name
    text_upper = text.upper()
    tracked_tickers = set(COMPANY_TICKER_MAP.values())

    for ticker in tracked_tickers:
        if f"${ticker}" in text_upper or \
           f" {ticker} " in text_upper or \
           f" {ticker}," in text_upper:
            found_tickers.add(ticker)

    return list(found_tickers)


def run_ner_pipeline(batch_size: int = 50) -> dict:
    """
    Enriches news_articles with ticker symbols using NER.

    Processes articles where ticker_symbols is NULL
    (RSS feed articles — no symbol set at ingestion).

    Flow:
    ┌──────────────────────────────────────────────────┐
    │ 1. Query RDS for articles with NULL ticker       │
    │ 2. Run spaCy NER on headline + body              │
    │ 3. Map company names → ticker symbols            │
    │ 4. Update ticker_symbols column in RDS           │
    └──────────────────────────────────────────────────┘

    Returns dict with processing summary.
    """
    if not nlp:
        return {"status": "error", "reason": "spacy not loaded"}

    db: Session = SessionLocal()
    processed = 0
    enriched  = 0

    try:
        # ── Get articles with no ticker symbols ───────────
        articles = db.query(NewsArticle).filter(
            NewsArticle.ticker_symbols == None
        ).limit(batch_size).all()

        if not articles:
            return {"status": "no_articles_to_enrich", "enriched": 0}

        for article in articles:
            # ── Combine headline + body for more context ──
            text = f"{article.headline} {article.body or ''}"

            # ── Extract tickers ───────────────────────────
            tickers = extract_tickers_from_text(text)
            processed += 1

            if tickers:
                # Join as comma-separated string
                article.ticker_symbols = ",".join(sorted(tickers))
                enriched += 1
            else:
                # Set to "NONE" so we don't re-process this
                # article repeatedly on every run
                article.ticker_symbols = "NONE"

        db.commit()

        logger.info(
            "ner_pipeline_completed",
            extra={
                "processed": processed,
                "enriched":  enriched
            }
        )

        return {
            "status":    "success",
            "processed": processed,
            "enriched":  enriched
        }

    except Exception as e:
        db.rollback()
        logger.error(
            "ner_pipeline_error",
            extra={"error": str(e)}
        )
        return {"status": "error", "error": str(e)}

    finally:
        db.close()