# path: app/schemas/stock.py

# =========================================================
# STOCK SCHEMAS — Pydantic models for API validation
# =========================================================
#
# These schemas are SEPARATE from SQLAlchemy models.
#
# SQLAlchemy model (app/models/stock.py):
#   - maps to database table
#   - used for DB read/write operations
#
# Pydantic schema (this file):
#   - validates incoming API requests
#   - shapes outgoing API responses
#   - controls exactly what data the API exposes
#
# Why separate?
#   Your DB table might have 20 columns.
#   Your API might only expose 8 of them.
#   Schemas give you that control cleanly.

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


# =========================================================
# BASE SCHEMA
# =========================================================
#
# StockBase contains fields shared across ALL stock schemas.
# Both create and response schemas inherit from this.
#
# This avoids repeating the same field definitions
# in every schema — DRY (Don't Repeat Yourself) principle.
class StockBase(BaseModel):

    # symbol: the stock ticker
    #
    # Field() adds extra validation and metadata:
    # - min_length=1: cannot be empty string
    # - max_length=10: AAPL is 4 chars, longest are ~5
    # - description: shows in /docs Swagger UI
    # - examples: shows example values in /docs
    symbol: str = Field(
        ...,                          # ... means required, no default
        min_length=1,
        max_length=10,
        description="Stock ticker symbol",
        examples=["AAPL", "MSFT"]
    )

    # company_name: full legal name
    company_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full company name",
        examples=["Apple Inc.", "Microsoft Corporation"]
    )

    # Optional fields — can be None if not provided
    # Optional[str] = None means: string or None, defaults to None
    sector: Optional[str] = Field(
        None,
        max_length=100,
        description="Business sector",
        examples=["Technology", "Healthcare"]
    )

    industry: Optional[str] = Field(
        None,
        max_length=100,
        description="Industry within sector",
        examples=["Consumer Electronics", "Software"]
    )


# =========================================================
# CREATE SCHEMA — used when POST /api/stocks is called
# =========================================================
#
# This is what the API ACCEPTS in the request body.
#
# Example request body:
# {
#   "symbol": "TSLA",
#   "company_name": "Tesla Inc.",
#   "sector": "Consumer Discretionary"
# }
#
# Inherits symbol, company_name, sector, industry
# from StockBase — no need to repeat them.
class StockCreate(StockBase):

    # @field_validator runs custom validation logic
    # on a specific field after pydantic's built-in checks.
    #
    # Here we force symbol to uppercase automatically.
    # So if someone sends "aapl", it becomes "AAPL".
    # mode="before" means: run this BEFORE pydantic validates
    @field_validator("symbol", mode="before")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        """
        Auto-converts symbol to uppercase.

        Why: stock symbols are always uppercase by convention.
        This prevents duplicate entries like 'aapl' and 'AAPL'.
        """
        return value.upper().strip()


# =========================================================
# UPDATE SCHEMA — used when PATCH /api/stocks/{id} is called
# =========================================================
#
# All fields are Optional here because PATCH means
# "update only what I send".
#
# If you only want to update sector, you send:
# { "sector": "Technology" }
# Everything else stays unchanged in the DB.
class StockUpdate(BaseModel):

    # Every field is Optional with None default
    # so the route can tell which fields were actually sent
    company_name: Optional[str] = Field(None, max_length=255)
    sector: Optional[str] = Field(None, max_length=100)
    industry: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None


# =========================================================
# RESPONSE SCHEMA — used when returning data to the client
# =========================================================
#
# This is what the API RETURNS in the response body.
#
# It includes DB-generated fields (id, created_at)
# that don't exist when creating a stock.
#
# Notice: description and updated_at are intentionally
# excluded — too verbose for a list response.
class StockResponse(StockBase):

    # DB-generated fields included in the response
    id: int
    is_active: bool
    created_at: datetime

    # model_config tells pydantic how to behave
    #
    # from_attributes=True is CRITICAL for FastAPI + SQLAlchemy.
    # Without it, pydantic cannot read SQLAlchemy model objects.
    #
    # SQLAlchemy returns objects like: stock.symbol
    # Pydantic by default expects dicts like: {"symbol": "AAPL"}
    # from_attributes=True allows pydantic to read object attributes
    model_config = {"from_attributes": True}


# =========================================================
# LIST RESPONSE SCHEMA — wraps a list of stocks
# =========================================================
#
# Instead of returning a raw list [], we wrap it in an object.
# This gives us room to add metadata (total count, pagination)
# without breaking the API contract later.
#
# Response shape:
# {
#   "stocks": [...],
#   "total": 10
# }
class StockListResponse(BaseModel):

    stocks: list[StockResponse]

    # total: how many stocks are in the DB
    # useful for the frontend to show "Showing 10 stocks"
    total: int