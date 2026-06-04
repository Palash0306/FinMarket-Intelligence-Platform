# path: scripts/seed_prices.py

# =========================================================
# SEED SCRIPT — Initial Price Data
# =========================================================
#
# Fetches 5 days of historical prices from yfinance
# and writes them directly to ClickHouse ohlcv table.
#
# Usage:
#   python scripts/seed_prices.py
#
# Run this:
# - When ClickHouse is empty and you need initial data
# - After resetting ClickHouse
# - To backfill missing price data
#
# Safe to run multiple times — ClickHouse MergeTree
# engine handles duplicate rows gracefully.
#
# Why run on Mac (not inside Docker)?
# yfinance works better on Mac — Docker IPs sometimes
# get blocked by Yahoo Finance servers.
# ClickHouse is reachable at localhost:9000 via Docker
# port mapping, so we override CLICKHOUSE_HOST here.

import sys
import os

# ── Add project root to Python path ──────────────────────
#
# Same pattern as seed_stocks.py.
# This script lives in scripts/ but imports from app/
# so we add the parent directory to sys.path first.
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# ── Override ClickHouse host for local execution ──────────
#
# MUST come before importing app modules.
# config.py reads settings at import time.
#
# Inside Docker: ClickHouse host = "clickhouse" (service name)
# On your Mac:   ClickHouse host = "localhost" (port mapped)
#
# Without this line you get:
# "nodename nor servname provided" error
os.environ["CLICKHOUSE_HOST"] = "localhost"

import yfinance as yf
from datetime import datetime, timezone
from app.db.clickhouse import get_clickhouse_client
from app.db.session import SessionLocal
from app.models.stock import Stock


def get_active_symbols() -> list[str]:
    """
    Reads active stock symbols from RDS stocks table.

    Same pattern as seed_stocks.py — opens a DB session,
    queries the stocks table, returns symbol list.

    Connects to:
    session.py → RDS connection
    Stock model → stocks table
    """
    db = SessionLocal()
    try:
        stocks = db.query(Stock).filter(
            Stock.is_active == True
        ).all()
        return [stock.symbol for stock in stocks]
    finally:
        db.close()


def seed_prices() -> None:
    """
    Fetches 5 days of price data and inserts into ClickHouse.

    Flow:
    get symbols from RDS stocks table
        ↓
    yfinance fetches OHLCV from Yahoo Finance
        ↓
    rows built as list of tuples
        ↓
    ClickHouse INSERT into ohlcv table
        ↓
    verify row counts per symbol
    """

    # ── Get symbols from RDS ──────────────────────────────
    #
    # Reads from the stocks table seeded by seed_stocks.py
    # Returns ['AAPL', 'MSFT', 'GOOGL', ...]
    print("Reading active symbols from RDS...")
    symbols = get_active_symbols()

    if not symbols:
        print("No active symbols found in RDS stocks table.")
        print("Run scripts/seed_stocks.py first.")
        return

    print(f"Found {len(symbols)} symbols: {symbols}")
    print()

    # ── Fetch prices from yfinance ────────────────────────
    print("Fetching 5 days of price data from yfinance...")
    rows = []

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)

            # period="5d"    = last 5 trading days
            # interval="1d"  = daily candles
            # auto_adjust=True = adjust for splits/dividends
            hist = ticker.history(
                period="5d",
                interval="1d",
                auto_adjust=True
            )

            if hist.empty:
                print(f"  {symbol}: no data returned")
                continue

            # ── Build rows for ClickHouse insert ──────────
            #
            # Each row = one tuple matching ohlcv column order:
            # (symbol, timestamp, open, high, low, close, volume, source)
            for idx, row in hist.iterrows():

                def safe_float(val) -> float:
                    """
                    Converts any numpy/pandas value to plain float.
                    yfinance 1.4.x sometimes returns numpy types
                    which ClickHouse driver cannot serialise.
                    .item() converts numpy scalar → Python scalar.
                    """
                    try:
                        if hasattr(val, 'item'):
                            return round(float(val.item()), 4)
                        return round(float(val), 4)
                    except Exception:
                        return 0.0

                rows.append((
                    symbol,
                    # idx is a pandas Timestamp
                    # .to_pydatetime() converts to Python datetime
                    # .replace(tzinfo=timezone.utc) adds timezone
                    idx.to_pydatetime().replace(tzinfo=timezone.utc),
                    safe_float(row["Open"]),
                    safe_float(row["High"]),
                    safe_float(row["Low"]),
                    safe_float(row["Close"]),
                    safe_float(row["Volume"]),
                    "yfinance"
                ))

            print(f"  {symbol}: {len(hist)} rows fetched")

        except Exception as e:
            print(f"  {symbol}: ERROR — {e}")
            continue

    # ── Check we have data ────────────────────────────────
    if not rows:
        print("\nNo price data fetched.")
        print("Possible reasons:")
        print("  1. Markets closed and no recent data")
        print("  2. yfinance blocked — try again in a few minutes")
        return

    print(f"\nTotal rows ready to insert: {len(rows)}")

    # ── Insert into ClickHouse ────────────────────────────
    #
    # get_clickhouse_client() uses CLICKHOUSE_HOST=localhost
    # which we set at the top of this file.
    # Without that override it would try "clickhouse:9000"
    # which only resolves inside Docker.
    print("Connecting to ClickHouse at localhost:9000...")

    try:
        client = get_clickhouse_client()

        client.execute(
            """
            INSERT INTO ohlcv
            (symbol, timestamp, open, high, low, close, volume, source)
            VALUES
            """,
            rows
        )
        print(f"Inserted {len(rows)} rows successfully.")

    except Exception as e:
        print(f"ClickHouse insert failed: {e}")
        print("Make sure Docker is running: docker compose up -d")
        return

    # ── Verify ────────────────────────────────────────────
    print()
    print("Verifying ClickHouse contents...")

    result = client.execute(
        """
        SELECT
            symbol,
            count()          AS rows,
            min(timestamp)   AS earliest,
            max(timestamp)   AS latest,
            max(close)       AS latest_close
        FROM ohlcv
        GROUP BY symbol
        ORDER BY symbol
        """
    )

    print()
    print("ClickHouse ohlcv table:")
    print(f"{'Symbol':<8} {'Rows':<6} {'Latest Close':<14} {'Latest Date'}")
    print("-" * 50)
    for row in result:
        print(
            f"  {row[0]:<6} "
            f"{row[1]:<6} "
            f"${row[4]:<12} "
            f"{str(row[3])[:10]}"
        )

    print()
    print("Done. Verify via API:")
    print("  curl http://localhost:8000/api/prices/AAPL")


if __name__ == "__main__":
    seed_prices()