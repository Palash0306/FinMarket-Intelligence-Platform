# path: app/models/stock.py

# =========================================================
# STOCK MODEL
# =========================================================
#
# This model represents a stock/company we are tracking.
#
# It is the root entity in our data model.
# All other tables (prices, forecasts, sentiment)
# will have a foreign key pointing to this table.
#
# Database table name: stocks
#
# Example rows:
# | id | symbol | company_name        | sector      | is_active |
# |----|--------|---------------------|-------------|-----------|
# |  1 | AAPL   | Apple Inc.          | Technology  | true      |
# |  2 | MSFT   | Microsoft Corp.     | Technology  | true      |
# |  3 | GOOGL  | Alphabet Inc.       | Technology  | true      |

# Column:       defines a table column
# Integer:      SQL INTEGER type — whole numbers
# String:       SQL VARCHAR type — text with max length
# Boolean:      SQL BOOLEAN type — true/false
# Text:         SQL TEXT type — unlimited length text
# Index:        creates a DB index for faster queries
from sqlalchemy import Column, Integer, String, Boolean, Text, Index

# Mapped:       type hint for ORM mapped columns (SQLAlchemy 2.0)
# mapped_column: modern way to define columns with type hints
from sqlalchemy.orm import Mapped, mapped_column

# Base:         our root ORM class all models inherit from
# TimestampMixin: adds created_at and updated_at automatically
from app.models.base import Base, TimestampMixin


class Stock(Base, TimestampMixin):
    """
    Represents a stock/company being tracked.

    Inherits from:
    - Base: registers this class as a SQLAlchemy ORM model
    - TimestampMixin: adds created_at and updated_at columns

    Table name: stocks
    """

    # ── Table name ────────────────────────────────────────
    #
    # __tablename__ tells SQLAlchemy what to name the
    # table in PostgreSQL.
    #
    # Convention: lowercase, plural, underscored.
    # Python class = Stock (singular, PascalCase)
    # DB table     = stocks (plural, lowercase)
    __tablename__ = "stocks"


    # ── Primary Key ───────────────────────────────────────
    #
    # Every table needs a primary key — a unique identifier
    # for each row.
    #
    # Integer primary key:
    # - auto-increments (1, 2, 3...)
    # - PostgreSQL handles this automatically
    # - index=True: PostgreSQL auto-indexes primary keys
    #   for fast lookups
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="Auto-incrementing unique identifier"
    )


    # ── Stock Symbol ──────────────────────────────────────
    #
    # The ticker symbol — unique short code for a stock.
    # Examples: AAPL, MSFT, GOOGL, TSLA
    #
    # String(10): max 10 characters (symbols are short)
    # unique=True: no two stocks can have the same symbol
    # nullable=False: every stock must have a symbol
    # index=True: we query by symbol constantly,
    #             so this index makes lookups very fast.
    #
    # Without index: PostgreSQL scans every row → slow
    # With index:    PostgreSQL jumps directly to row → fast
    symbol: Mapped[str] = mapped_column(
        String(10),
        unique=True,
        nullable=False,
        index=True,
        comment="Stock ticker symbol e.g. AAPL, MSFT"
    )


    # ── Company Name ─────────────────────────────────────
    #
    # Full legal name of the company.
    # String(255): max 255 characters
    # nullable=False: required field
    company_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Full company name e.g. Apple Inc."
    )


    # ── Sector ───────────────────────────────────────────
    #
    # Business sector the company belongs to.
    # Examples: Technology, Healthcare, Finance
    #
    # nullable=True: optional — we may not know it yet
    sector: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Business sector e.g. Technology, Healthcare"
    )


    # ── Industry ─────────────────────────────────────────
    #
    # More specific than sector.
    # Example:
    #   sector   = Technology
    #   industry = Consumer Electronics
    industry: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Industry within sector e.g. Consumer Electronics"
    )


    # ── Description ──────────────────────────────────────
    #
    # Text: unlimited length (unlike String which has a limit)
    # Used to store a brief company description.
    # nullable=True: optional field
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Brief company description"
    )


    # ── Active Flag ───────────────────────────────────────
    #
    # Boolean flag to enable/disable tracking a stock
    # without deleting it from the database.
    #
    # This is called a "soft delete" pattern —
    # instead of DELETE FROM stocks WHERE symbol='AAPL'
    # we set is_active = False.
    #
    # Why soft delete?
    # - preserves historical data
    # - can reactivate without data loss
    # - safer in production systems
    #
    # server_default="true": new stocks are active by default
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False,
        comment="Whether this stock is actively being tracked"
    )


    # ── Table-level Index ─────────────────────────────────
    #
    # __table_args__ defines table-level configurations.
    #
    # This composite index speeds up queries that filter
    # by both sector AND is_active together.
    #
    # Example query that benefits from this index:
    #
    # SELECT * FROM stocks
    # WHERE sector = 'Technology' AND is_active = true
    #
    # Without index: full table scan
    # With index:    direct lookup
    __table_args__ = (
        Index(
            "ix_stocks_sector_active",  # index name
            "sector",                   # first column
            "is_active"                 # second column
        ),
    )


    def __repr__(self) -> str:
        """
        String representation of a Stock object.

        Used when printing or debugging.

        Example:
            stock = Stock(symbol="AAPL", company_name="Apple Inc.")
            print(stock)
            # Output: <Stock AAPL - Apple Inc.>
        """
        return f"<Stock {self.symbol} - {self.company_name}>"