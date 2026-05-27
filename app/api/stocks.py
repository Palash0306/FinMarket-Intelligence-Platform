# path: app/api/stocks.py

# =========================================================
# STOCKS API ROUTER
# =========================================================
#
# This file handles all HTTP endpoints for stocks:
#
# GET    /api/stocks          → list all stocks
# GET    /api/stocks/{symbol} → get one stock by symbol
# POST   /api/stocks          → create a new stock
# PATCH  /api/stocks/{symbol} → update a stock
# DELETE /api/stocks/{symbol} → soft delete a stock
#
# Each function is a "route handler" — it runs when
# a matching HTTP request comes in.

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional

# APIRouter creates a mini FastAPI app for this group of routes
# prefix="/api/stocks" means all routes here start with /api/stocks
# tags=["Stocks"] groups them in the /docs Swagger UI
from app.db.session import get_db
from app.models.stock import Stock
from app.schemas.stock import (
    StockCreate,
    StockUpdate,
    StockResponse,
    StockListResponse
)

# ── Create the router ─────────────────────────────────────
#
# This router is registered in main.py.
# All routes defined below automatically get the /api/stocks prefix.
router = APIRouter(
    prefix="/api/stocks",
    tags=["Stocks"]
)


# =========================================================
# GET /api/stocks — list all stocks
# =========================================================
#
# Query parameters (optional filters):
# - sector: filter by sector   e.g. ?sector=Technology
# - active_only: only return active stocks (default True)
#
# Example requests:
# GET /api/stocks
# GET /api/stocks?sector=Technology
# GET /api/stocks?active_only=false
@router.get(
    "/",
    response_model=StockListResponse,  # validates + shapes the response
    summary="List all tracked stocks"
)
def get_stocks(
    # Depends(get_db) injects a DB session automatically
    # FastAPI calls get_db(), gets a session, passes it here
    db: Session = Depends(get_db),

    # Query parameters — optional filters from the URL
    # Query() adds validation and Swagger UI documentation
    sector: Optional[str] = Query(
        None,
        description="Filter by sector e.g. Technology"
    ),
    active_only: bool = Query(
        True,
        description="If true, only return active stocks"
    )
):
    """
    Returns all stocks being tracked.

    Optional filters:
    - sector: filter by business sector
    - active_only: exclude deactivated stocks (default: true)
    """

    # ── Start building the query ──────────────────────────
    #
    # db.query(Stock) is like:
    # SELECT * FROM stocks
    #
    # We chain .filter() to add WHERE clauses.
    # Nothing hits the DB until .all() is called at the end.
    query = db.query(Stock)

    # ── Apply filters if provided ─────────────────────────
    if active_only:
        # WHERE is_active = true
        query = query.filter(Stock.is_active == True)

    if sector:
        # WHERE sector = 'Technology'
        # ilike = case-insensitive LIKE
        # so ?sector=technology also matches 'Technology'
        query = query.filter(Stock.sector.ilike(f"%{sector}%"))

    # ── Execute query ─────────────────────────────────────
    #
    # .all() fires the SQL and returns a list of Stock objects
    stocks = query.order_by(Stock.symbol).all()

    # ── Return wrapped response ───────────────────────────
    #
    # StockListResponse expects:
    # { "stocks": [...], "total": 10 }
    return StockListResponse(
        stocks=stocks,
        total=len(stocks)
    )


# =========================================================
# GET /api/stocks/{symbol} — get one stock
# =========================================================
#
# {symbol} is a path parameter — part of the URL itself.
# GET /api/stocks/AAPL  → symbol = "AAPL"
# GET /api/stocks/MSFT  → symbol = "MSFT"
@router.get(
    "/{symbol}",
    response_model=StockResponse,
    summary="Get a single stock by symbol"
)
def get_stock(
    symbol: str,          # FastAPI extracts this from the URL path
    db: Session = Depends(get_db)
):
    """
    Returns a single stock by its ticker symbol.

    Raises 404 if the symbol is not found.
    """

    # .first() returns the first match or None
    # .upper() ensures AAPL matches even if URL was /api/stocks/aapl
    stock = db.query(Stock).filter(
        Stock.symbol == symbol.upper()
    ).first()

    # ── Handle not found ──────────────────────────────────
    #
    # HTTPException tells FastAPI to return an error response.
    # status_code=404: standard "not found" HTTP status
    # detail: the error message the client receives
    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stock '{symbol.upper()}' not found"
        )

    return stock


# =========================================================
# POST /api/stocks — create a new stock
# =========================================================
#
# Request body must match StockCreate schema.
# Returns the created stock with its DB-assigned id.
#
# status_code=201: "Created" — more specific than 200 "OK"
@router.post(
    "/",
    response_model=StockResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new stock to track"
)
def create_stock(
    stock_data: StockCreate,    # pydantic validates the request body
    db: Session = Depends(get_db)
):
    """
    Adds a new stock to the tracking list.

    Raises 409 if the symbol already exists.
    """

    # ── Check for duplicate ───────────────────────────────
    #
    # We don't want two rows with symbol='AAPL'.
    # The DB has a unique constraint too, but checking here
    # gives a cleaner error message to the API client.
    existing = db.query(Stock).filter(
        Stock.symbol == stock_data.symbol
    ).first()

    if existing:
        # 409 Conflict: resource already exists
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Stock '{stock_data.symbol}' already exists"
        )

    # ── Create Stock object ───────────────────────────────
    #
    # model_dump() converts the pydantic schema to a dict:
    # {"symbol": "TSLA", "company_name": "Tesla Inc.", ...}
    #
    # **stock_data.model_dump() unpacks that dict as kwargs:
    # Stock(symbol="TSLA", company_name="Tesla Inc.", ...)
    stock = Stock(**stock_data.model_dump())

    # ── Save to DB ────────────────────────────────────────
    db.add(stock)
    db.commit()

    # db.refresh() reloads the object from DB
    # This populates DB-generated fields like id and created_at
    # which don't exist on the Python object until after commit
    db.refresh(stock)

    return stock


# =========================================================
# PATCH /api/stocks/{symbol} — update a stock
# =========================================================
#
# PATCH means partial update — only send fields you want changed.
# PUT means full replacement — send all fields.
# We use PATCH because it's more flexible.
@router.patch(
    "/{symbol}",
    response_model=StockResponse,
    summary="Update a stock's details"
)
def update_stock(
    symbol: str,
    stock_data: StockUpdate,    # all fields optional
    db: Session = Depends(get_db)
):
    """
    Updates one or more fields of an existing stock.

    Only the fields you send will be changed.
    """

    # ── Find the stock ────────────────────────────────────
    stock = db.query(Stock).filter(
        Stock.symbol == symbol.upper()
    ).first()

    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stock '{symbol.upper()}' not found"
        )

    # ── Apply only the fields that were sent ──────────────
    #
    # model_dump(exclude_unset=True) returns ONLY the fields
    # that were actually included in the request body.
    #
    # Example: if request was {"sector": "Technology"}
    # model_dump(exclude_unset=True) returns {"sector": "Technology"}
    # NOT {"sector": "Technology", "company_name": None, ...}
    #
    # Without exclude_unset=True, every unsent field would be
    # set to None, wiping out existing data.
    update_data = stock_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        # setattr(stock, "sector", "Technology")
        # is the same as: stock.sector = "Technology"
        # but works dynamically for any field name
        setattr(stock, field, value)

    db.commit()
    db.refresh(stock)

    return stock


# =========================================================
# DELETE /api/stocks/{symbol} — soft delete
# =========================================================
#
# We never hard delete (DELETE FROM stocks WHERE...).
# We soft delete: set is_active = False.
# Data is preserved, stock just stops being tracked.
@router.delete(
    "/{symbol}",
    summary="Deactivate a stock (soft delete)"
)
def delete_stock(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    Deactivates a stock — sets is_active to False.

    The stock remains in the database for historical data.
    """

    stock = db.query(Stock).filter(
        Stock.symbol == symbol.upper()
    ).first()

    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stock '{symbol.upper()}' not found"
        )

    # Soft delete — just flip the flag
    stock.is_active = False
    db.commit()

    # Return a simple confirmation message
    return {
        "message": f"Stock '{symbol.upper()}' deactivated successfully",
        "symbol": symbol.upper()
    }