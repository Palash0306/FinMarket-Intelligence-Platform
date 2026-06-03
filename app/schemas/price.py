# path: app/schemas/price.py

# =========================================================
# PRICE SCHEMAS — Pydantic models for price API
# =========================================================
#
# What is this file in plain English?
#
# This file defines the SHAPE of price data that comes
# OUT of your API. Like a stencil — data from ClickHouse
# gets pressed through this stencil before being sent
# to the user. Only the fields in the stencil come out.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# ClickHouse ohlcv table ──────────────────────────────┐
# (rows written by price_consumer.py Day 1)            │
#       ↓ raw dict from ClickHouse                     │
# app/api/prices.py                                    │
#       ↓ wraps in THIS schema                         │
# PriceResponse / PriceHistoryResponse                 │
#       ↓ clean JSON sent to                           │
# Browser / Dashboard / Streamlit (Phase 5)            │
#                                                      │
# Phase 3 also reads ClickHouse directly ──────────────┘
# (ML models don't go through the API)
# ─────────────────────────────────────────────────────────

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PriceResponse(BaseModel):
    """
    Shape of ONE price record returned by the API.

    One row = one OHLCV snapshot for one stock
    at one point in time.

    OHLCV explained in plain English:
    - Open:   price at the START of the 5-min candle
    - High:   HIGHEST price during the 5-min candle
    - Low:    LOWEST price during the 5-min candle
    - Close:  price at the END of the 5-min candle
    - Volume: how many shares traded during that 5 min

    Connects to:
    ClickHouse ohlcv table columns → these exact fields
    price_consumer.py wrote them → prices.py reads them
    """

    # symbol: which stock this price is for
    # e.g. "AAPL", "MSFT"
    symbol: str = Field(
        description="Stock ticker symbol"
    )

    # timestamp: when this price snapshot was taken
    # ClickHouse stores as DateTime, Pydantic converts to Python datetime
    timestamp: datetime = Field(
        description="When this price was recorded"
    )

    # OHLCV fields — all Float, all from ClickHouse
    open:   float = Field(description="Opening price")
    high:   float = Field(description="Highest price in period")
    low:    float = Field(description="Lowest price in period")
    close:  float = Field(description="Closing price")
    volume: float = Field(description="Trading volume")

    # source: which data provider gave us this price
    # Currently "yfinance" — could be others in future
    source: str = Field(
        default="yfinance",
        description="Data source"
    )

    model_config = {"from_attributes": True}


class LatestPriceResponse(BaseModel):
    """
    Shape of the LATEST price response.

    Adds extra context fields on top of basic OHLCV:
    - company_name: human readable name from RDS stocks table
    - price_change: how much price moved since last reading
    - price_change_pct: percentage change

    Connects to:
    RDS stocks table → company_name
    ClickHouse ohlcv → all price fields
    prices.py calculates change → adds to response
    """

    symbol:           str
    company_name:     Optional[str] = None
    timestamp:        datetime
    open:             float
    high:             float
    low:              float
    close:            float
    volume:           float

    # price_change and price_change_pct:
    # Calculated in prices.py by comparing
    # latest close to previous close.
    # None if not enough data yet.
    price_change:     Optional[float] = None
    price_change_pct: Optional[float] = None
    source:           str = "yfinance"

    model_config = {"from_attributes": True}


class PriceHistoryResponse(BaseModel):
    """
    Shape of the historical prices response.

    Returns a list of price records + summary metadata.

    Example response:
    {
      "symbol": "AAPL",
      "period_days": 30,
      "total_records": 864,
      "prices": [ {...}, {...}, ... ]
    }

    Connects to:
    ClickHouse ohlcv → prices list (many rows)
    prices.py counts rows → total_records
    """

    symbol:        str
    period_days:   int
    total_records: int

    # prices: list of individual PriceResponse objects
    # Each one is one 5-minute candle
    prices: list[PriceResponse]


class PriceSummaryResponse(BaseModel):
    """
    Shape of a daily price summary.

    Aggregated from many 5-min candles into one day.
    Used by the dashboard for charts.

    Connects to:
    ClickHouse → prices.py runs AVG/MAX/MIN/SUM query
    → this schema shapes the result
    """

    symbol:      str
    date:        str
    open:        float
    high:        float
    low:         float
    close:       float
    volume:      float
    avg_close:   float