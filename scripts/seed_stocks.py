# path: scripts/seed_stocks.py

# =========================================================
# SEED SCRIPT — Initial Stock Data
# =========================================================
#
# A seed script populates the database with initial data.
#
# Run once after migrations to have a working dataset.
#
# Usage:
#   python scripts/seed_stocks.py
#
# Safe to run multiple times — uses upsert logic
# (INSERT ... ON CONFLICT DO NOTHING)
# so duplicate symbols are skipped, not duplicated.

import sys
import os

# ── Add project root to Python path ──────────────────────
#
# This script lives in scripts/ but needs to import from app/
# Adding the parent directory to sys.path allows:
#   from app.config import settings
# to work correctly when running from the scripts/ folder.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.stock import Stock


# ── Stock data to seed ────────────────────────────────────
#
# These are the companies we will track throughout the project.
# Mix of sectors to make the ML and sentiment analysis
# more interesting and diverse.
INITIAL_STOCKS = [
    # Technology
    {
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "description": "Designs and sells smartphones, computers, and software."
    },
    {
        "symbol": "MSFT",
        "company_name": "Microsoft Corporation",
        "sector": "Technology",
        "industry": "Software",
        "description": "Develops software, cloud services, and hardware."
    },
    {
        "symbol": "GOOGL",
        "company_name": "Alphabet Inc.",
        "sector": "Technology",
        "industry": "Internet Services",
        "description": "Parent company of Google — search, ads, and cloud."
    },
    {
        "symbol": "NVDA",
        "company_name": "NVIDIA Corporation",
        "sector": "Technology",
        "industry": "Semiconductors",
        "description": "Designs GPUs for gaming, AI, and data centers."
    },
    {
        "symbol": "META",
        "company_name": "Meta Platforms Inc.",
        "sector": "Technology",
        "industry": "Social Media",
        "description": "Operates Facebook, Instagram, and WhatsApp."
    },
    # Finance
    {
        "symbol": "JPM",
        "company_name": "JPMorgan Chase & Co.",
        "sector": "Finance",
        "industry": "Banking",
        "description": "Largest US bank by assets."
    },
    {
        "symbol": "GS",
        "company_name": "Goldman Sachs Group Inc.",
        "sector": "Finance",
        "industry": "Investment Banking",
        "description": "Global investment banking and securities firm."
    },
    # Healthcare
    {
        "symbol": "JNJ",
        "company_name": "Johnson & Johnson",
        "sector": "Healthcare",
        "industry": "Pharmaceuticals",
        "description": "Develops pharmaceuticals, medical devices, and consumer products."
    },
    # Energy
    {
        "symbol": "XOM",
        "company_name": "Exxon Mobil Corporation",
        "sector": "Energy",
        "industry": "Oil & Gas",
        "description": "One of the world's largest oil and gas companies."
    },
    # Consumer
    {
        "symbol": "AMZN",
        "company_name": "Amazon.com Inc.",
        "sector": "Consumer Discretionary",
        "industry": "E-Commerce",
        "description": "E-commerce, cloud computing (AWS), and digital streaming."
    },
]


def seed_stocks() -> None:
    """
    Insert initial stocks into the database.

    Uses a get-or-create pattern:
    - If symbol already exists → skip it
    - If symbol is new → insert it

    This makes the script safe to run multiple times.
    """

    # ── Open DB session ───────────────────────────────────
    #
    # SessionLocal() creates a new database connection.
    # We wrap it in try/finally to always close it,
    # even if an error occurs during seeding.
    db = SessionLocal()

    try:
        print("Seeding stocks table...")

        inserted = 0   # track how many new records added
        skipped  = 0   # track how many already existed

        for stock_data in INITIAL_STOCKS:

            # ── Check if stock already exists ─────────────
            #
            # Query the DB for this symbol.
            # .first() returns the first match or None.
            existing = db.query(Stock).filter(
                Stock.symbol == stock_data["symbol"]
            ).first()

            if existing:
                # Stock already in DB — skip it
                print(f"  Skipping {stock_data['symbol']} — already exists")
                skipped += 1
                continue

            # ── Create new Stock object ───────────────────
            #
            # **stock_data unpacks the dictionary as keyword args:
            #
            # Stock(**stock_data) is equivalent to:
            # Stock(
            #   symbol="AAPL",
            #   company_name="Apple Inc.",
            #   ...
            # )
            stock = Stock(**stock_data)

            # ── Add to session ────────────────────────────
            #
            # db.add() stages the object for insertion.
            # Nothing hits the DB yet — it's queued.
            db.add(stock)
            print(f"  Adding {stock_data['symbol']} — {stock_data['company_name']}")
            inserted += 1

        # ── Commit all inserts at once ────────────────────
        #
        # db.commit() flushes all staged changes to the DB
        # in a single transaction.
        #
        # If any insert fails, the whole transaction rolls back
        # — no partial data is written.
        db.commit()

        print(f"\nDone. {inserted} stocks inserted, {skipped} skipped.")

    except Exception as e:
        # ── Rollback on error ─────────────────────────────
        #
        # If anything goes wrong, undo all staged changes.
        # Prevents partial/corrupt data in the database.
        db.rollback()
        print(f"Error seeding stocks: {e}")
        raise

    finally:
        # ── Always close the session ──────────────────────
        #
        # Releases the database connection back to the pool.
        # This runs whether the try block succeeded or failed.
        db.close()


if __name__ == "__main__":
    seed_stocks()