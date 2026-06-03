# path: app/api/prices.py

# =========================================================
# PRICES API — Endpoints to read ClickHouse price data
# =========================================================
#
# What does this file do in plain English?
#
# This is the front door to your price data.
# Users (or the dashboard) call these endpoints to get
# stock prices that were collected by stock_fetcher.py
# and stored in ClickHouse by price_consumer.py.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# app/db/clickhouse.py ────────────────────────────────┐
#   get_clickhouse_client() → connect to ClickHouse     │
#   (configured via config.py → .env)                  │
#       ↓                                              │
# app/models/stock.py ─────────────────────────────────┤
#   Stock model → validates symbol exists in RDS        │
#   (via session.py get_db())                          │
#       ↓                                              │
# app/schemas/price.py ────────────────────────────────┤
#   PriceResponse, LatestPriceResponse, etc.           │
#   shapes the data before sending to user             │
#       ↓                                              │
# THIS FILE (prices.py) ───────────────────────────────┘
#   defines the actual HTTP endpoints
#       ↓ registered in
# app/main.py → app.include_router(prices_router)
#       ↓ called by
# Browser / Streamlit dashboard (Phase 5)
# ML models (Phase 3) also read ClickHouse directly
#
# DATA FLOW FOR ONE REQUEST:
#
# GET /api/prices/AAPL
#       ↓
# validate AAPL exists in RDS stocks table
# (uses session.py + Stock model)
#       ↓
# query ClickHouse:
# SELECT * FROM ohlcv
# WHERE symbol = 'AAPL'
# ORDER BY timestamp DESC LIMIT 1
# (uses clickhouse.py)
#       ↓
# wrap result in LatestPriceResponse schema
# (uses schemas/price.py)
#       ↓
# return JSON to user
# ─────────────────────────────────────────────────────────

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.db.session import get_db
from app.db.clickhouse import get_clickhouse_client
from app.models.stock import Stock
from app.schemas.price import (
    LatestPriceResponse,
    PriceHistoryResponse,
    PriceResponse,
    PriceSummaryResponse
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Create the router ─────────────────────────────────────
#
# Same pattern as app/api/stocks.py from Phase 1.
# All routes here start with /api/prices
# All appear under "Prices" group in /docs
router = APIRouter(
    prefix="/api/prices",
    tags=["Prices"]
)


def validate_symbol(symbol: str, db: Session) -> Stock:
    """
    Helper: checks the symbol exists in RDS stocks table.

    Called by every endpoint before querying ClickHouse.
    If symbol doesn't exist → return 404 immediately.
    No point querying ClickHouse for a symbol we don't track.

    Connects to:
    session.py → db session passed in
    Stock model → queries stocks table
    """
    stock = db.query(Stock).filter(
        Stock.symbol == symbol.upper(),
        Stock.is_active == True
    ).first()

    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol '{symbol.upper()}' not found or not active"
        )
    return stock


# =========================================================
# GET /api/prices/{symbol} — latest price
# =========================================================
@router.get(
    "/{symbol}",
    response_model=LatestPriceResponse,
    summary="Get latest price for a stock"
)
def get_latest_price(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    Returns the most recent price record for a symbol.

    What it does step by step:
    1. Validates symbol exists in RDS (via Stock model)
    2. Queries ClickHouse for the latest row
    3. Calculates price change vs previous record
    4. Returns wrapped in LatestPriceResponse schema

    Example response:
    {
      "symbol": "AAPL",
      "company_name": "Apple Inc.",
      "close": 182.52,
      "price_change": +1.23,
      "price_change_pct": +0.68,
      ...
    }

    Connects to:
    validate_symbol() → RDS stocks table via session.py
    get_clickhouse_client() → ClickHouse ohlcv table
    LatestPriceResponse → schemas/price.py
    """

    # ── Step 1: validate symbol in RDS ───────────────────
    stock = validate_symbol(symbol, db)

    # ── Step 2: query ClickHouse for latest price ─────────
    #
    # get_clickhouse_client() from app/db/clickhouse.py
    # connects using settings from config.py → .env
    client = get_clickhouse_client()

    try:
        # ── Fetch the 2 most recent records ───────────────
        #
        # We need 2 records (not just 1) so we can
        # calculate the price change between them.
        # latest = records[0], previous = records[1]
        rows = client.execute(
            """
            SELECT
                symbol,
                timestamp,
                open,
                high,
                low,
                close,
                volume,
                source
            FROM ohlcv
            WHERE symbol = %(symbol)s
            ORDER BY timestamp DESC
            LIMIT 2
            """,
            {"symbol": symbol.upper()}
        )

    except Exception as e:
        logger.error(
            "clickhouse_query_error",
            extra={"symbol": symbol, "error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Price data temporarily unavailable"
        )

    # ── Handle no data yet ────────────────────────────────
    #
    # Stock exists in RDS but no prices in ClickHouse yet.
    # This happens if Celery hasn't run the first fetch yet.
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data yet for '{symbol.upper()}'. "
                   f"Data collection starts automatically."
        )

    # ── Build response ────────────────────────────────────
    #
    # ClickHouse returns raw tuples, not dicts.
    # We map tuple positions to field names manually.
    latest = rows[0]
    price_change     = None
    price_change_pct = None

    # Calculate change if we have a previous record
    if len(rows) >= 2:
        prev_close   = rows[1][5]  # index 5 = close column
        curr_close   = latest[5]
        price_change = round(curr_close - prev_close, 4)

        # Avoid division by zero
        if prev_close != 0:
            price_change_pct = round(
                (price_change / prev_close) * 100, 2
            )

    logger.info(
        "latest_price_fetched",
        extra={"symbol": symbol, "close": latest[5]}
    )

    # ── Wrap in schema and return ─────────────────────────
    #
    # LatestPriceResponse is from schemas/price.py.
    # It validates the data and formats it as JSON.
    return LatestPriceResponse(
        symbol=latest[0],
        company_name=stock.company_name,
        timestamp=latest[1],
        open=latest[2],
        high=latest[3],
        low=latest[4],
        close=latest[5],
        volume=latest[6],
        price_change=price_change,
        price_change_pct=price_change_pct,
        source=latest[7]
    )


# =========================================================
# GET /api/prices/{symbol}/history — historical prices
# =========================================================
@router.get(
    "/{symbol}/history",
    response_model=PriceHistoryResponse,
    summary="Get price history for a stock"
)
def get_price_history(
    symbol: str,
    # Query parameter: ?days=30
    # Default 30 days, max 90 days
    # User controls how much history they want
    days: int = Query(
        default=30,
        ge=1,
        le=90,
        description="Number of days of history (1-90)"
    ),
    db: Session = Depends(get_db)
):
    """
    Returns historical price records for a symbol.

    Example:
    GET /api/prices/AAPL/history?days=7
    → returns all 5-min candles for AAPL last 7 days

    Connects to:
    validate_symbol() → RDS stocks table
    ClickHouse ohlcv → price history rows
    PriceHistoryResponse → schemas/price.py
    """

    validate_symbol(symbol, db)
    client = get_clickhouse_client()

    try:
        # ── Query ClickHouse for date range ───────────────
        #
        # now() - toIntervalDay(days) = X days ago
        # This is ClickHouse's date arithmetic syntax.
        # Equivalent to Python: datetime.now() - timedelta(days=days)
        rows = client.execute(
            """
            SELECT
                symbol,
                timestamp,
                open,
                high,
                low,
                close,
                volume,
                source
            FROM ohlcv
            WHERE symbol = %(symbol)s
              AND timestamp >= now() - toIntervalDay(%(days)s)
            ORDER BY timestamp ASC
            """,
            {"symbol": symbol.upper(), "days": days}
        )

    except Exception as e:
        logger.error(
            "clickhouse_history_error",
            extra={"symbol": symbol, "error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Price history temporarily unavailable"
        )

    # ── Convert raw tuples to PriceResponse objects ───────
    #
    # Each row from ClickHouse is a tuple like:
    # ("AAPL", datetime(...), 182.1, 183.5, 181.9, 182.5, 50000, "yfinance")
    # We map each tuple to a PriceResponse schema object.
    prices = [
        PriceResponse(
            symbol=row[0],
            timestamp=row[1],
            open=row[2],
            high=row[3],
            low=row[4],
            close=row[5],
            volume=row[6],
            source=row[7]
        )
        for row in rows
    ]

    logger.info(
        "price_history_fetched",
        extra={
            "symbol": symbol,
            "days": days,
            "records": len(prices)
        }
    )

    return PriceHistoryResponse(
        symbol=symbol.upper(),
        period_days=days,
        total_records=len(prices),
        prices=prices
    )


# =========================================================
# GET /api/prices/{symbol}/summary — daily summaries
# =========================================================
@router.get(
    "/{symbol}/summary",
    response_model=list[PriceSummaryResponse],
    summary="Get daily price summary for a stock"
)
def get_price_summary(
    symbol: str,
    days: int = Query(
        default=30,
        ge=1,
        le=90,
        description="Number of days"
    ),
    db: Session = Depends(get_db)
):
    """
    Returns daily aggregated prices.

    Aggregates many 5-min candles into one row per day:
    - open:      first price of the day
    - high:      highest price of the day
    - low:       lowest price of the day
    - close:     last price of the day
    - avg_close: average close price across the day
    - volume:    total volume for the day

    Used by the Phase 5 dashboard for daily candlestick charts.

    Connects to:
    ClickHouse → GROUP BY toDate(timestamp)
    → aggregation functions (MAX, MIN, SUM, AVG)
    PriceSummaryResponse → schemas/price.py
    """

    validate_symbol(symbol, db)
    client = get_clickhouse_client()

    try:
        # ── Aggregation query ─────────────────────────────
        #
        # toDate(timestamp) extracts just the date part.
        # argMin(open, timestamp)  = open price at earliest timestamp
        # argMax(close, timestamp) = close price at latest timestamp
        # These are ClickHouse-specific aggregate functions.
        rows = client.execute(
            """
            SELECT
                symbol,
                toDate(timestamp)        AS date,
                argMin(open, timestamp)  AS open,
                max(high)                AS high,
                min(low)                 AS low,
                argMax(close, timestamp) AS close,
                sum(volume)              AS volume,
                avg(close)               AS avg_close
            FROM ohlcv
            WHERE symbol = %(symbol)s
              AND timestamp >= now() - toIntervalDay(%(days)s)
            GROUP BY symbol, date
            ORDER BY date ASC
            """,
            {"symbol": symbol.upper(), "days": days}
        )

    except Exception as e:
        logger.error(
            "clickhouse_summary_error",
            extra={"symbol": symbol, "error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Price summary temporarily unavailable"
        )

    return [
        PriceSummaryResponse(
            symbol=row[0],
            date=str(row[1]),
            open=row[2],
            high=row[3],
            low=row[4],
            close=row[5],
            volume=row[6],
            avg_close=round(row[7], 4)
        )
        for row in rows
    ]


# =========================================================
# GET /api/prices/ — list all symbols with latest price
# =========================================================
@router.get(
    "/",
    summary="Get latest prices for all tracked stocks"
)
def get_all_latest_prices(
    db: Session = Depends(get_db)
):
    """
    Returns the latest price for every active stock.

    Used by the dashboard overview page to show
    a watchlist with current prices.

    Connects to:
    RDS stocks table → all active symbols
    ClickHouse ohlcv → latest price per symbol
    """

    # Get all active symbols from RDS
    stocks = db.query(Stock).filter(
        Stock.is_active == True
    ).all()

    if not stocks:
        return {"prices": [], "total": 0}

    client    = get_clickhouse_client()
    symbols   = [s.symbol for s in stocks]
    stock_map = {s.symbol: s.company_name for s in stocks}

    try:
        # ── Get latest price for ALL symbols at once ──────
        #
        # argMax(close, timestamp) = the close price at the
        # most recent timestamp — this is ClickHouse's way
        # of getting "the latest value" per group.
        #
        # IN (%(symbols)s) filters to only our tracked stocks.
        rows = client.execute(
            """
            SELECT
                symbol,
                argMax(close, timestamp)     AS latest_close,
                argMax(timestamp, timestamp) AS latest_ts
            FROM ohlcv
            WHERE symbol IN %(symbols)s
            GROUP BY symbol
            ORDER BY symbol ASC
            """,
            {"symbols": symbols}
        )

    except Exception as e:
        logger.error(
            "clickhouse_all_prices_error",
            extra={"error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Price data temporarily unavailable"
        )

    prices = [
        {
            "symbol":       row[0],
            "company_name": stock_map.get(row[0]),
            "close":        row[1],
            "timestamp":    row[2]
        }
        for row in rows
    ]

    logger.info(
        "all_prices_fetched",
        extra={"count": len(prices)}
    )

    return {"prices": prices, "total": len(prices)}