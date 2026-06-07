# path: app/api/forecasts.py

# =========================================================
# FORECASTS API
# =========================================================
#
# Exposes ML model predictions via REST endpoints.
#
# Connection chain:
# RDS forecasts table (written by prophet_model.py + xgb_model.py)
#       ↓ queried by THIS FILE
#       ↓ shaped by schemas/forecast.py
#       ↓ returned to
# Browser / Streamlit / Phase 4 RAG agent
#
# Endpoints:
# GET /api/forecasts/{symbol}        → Prophet 7-day forecast
# GET /api/forecasts/{symbol}/signal → XGBoost buy/sell signal
# POST /api/forecasts/{symbol}/run   → trigger forecast now

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.forecast import Forecast
from app.models.stock import Stock
from app.schemas.forecast import (
    ForecastResponse,
    ProphetForecastPoint,
    XGBSignalResponse
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/forecasts",
    tags=["Forecasts"]
)


def validate_symbol(symbol: str, db: Session) -> Stock:
    """Validates symbol exists in RDS stocks table."""
    stock = db.query(Stock).filter(
        Stock.symbol    == symbol.upper(),
        Stock.is_active == True
    ).first()
    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol '{symbol.upper()}' not found"
        )
    return stock


@router.get(
    "/{symbol}",
    response_model=ForecastResponse,
    summary="Get 7-day price forecast for a stock"
)
def get_forecast(symbol: str, db: Session = Depends(get_db)):
    """
    Returns Prophet 7-day price forecast + XGBoost signal.

    Data comes from RDS forecasts table populated by
    Celery tasks running prophet_model.py and xgb_model.py.

    If no forecast exists yet → 404 with instructions to trigger.
    """
    validate_symbol(symbol, db)

    # ── Fetch Prophet forecasts ───────────────────────────
    prophet_rows = db.query(Forecast).filter(
        Forecast.symbol     == symbol.upper(),
        Forecast.model_type == "prophet"
    ).order_by(Forecast.forecast_date.asc()).all()

    if not prophet_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No forecast for '{symbol.upper()}' yet. "
                f"POST /api/forecasts/{symbol.upper()}/run to generate."
            )
        )

    # ── Fetch XGBoost signal ──────────────────────────────
    xgb_row = db.query(Forecast).filter(
        Forecast.symbol     == symbol.upper(),
        Forecast.model_type == "xgboost"
    ).order_by(Forecast.forecast_date.desc()).first()

    # ── Build Prophet response ────────────────────────────
    prophet_forecasts = [
        ProphetForecastPoint(
            forecast_date   = row.forecast_date,
            predicted_price = row.predicted_price,
            lower_bound     = row.lower_bound,
            upper_bound     = row.upper_bound,
            mae             = row.mae
        )
        for row in prophet_rows
    ]

    # ── Build XGBoost response ────────────────────────────
    xgb_signal = None
    if xgb_row and xgb_row.direction_signal is not None:
        xgb_signal = XGBSignalResponse(
            symbol           = symbol.upper(),
            forecast_date    = xgb_row.forecast_date,
            direction_signal = xgb_row.direction_signal,
            signal_label     = "UP" if xgb_row.direction_signal == 1 else "DOWN",
            confidence       = xgb_row.confidence or 0.0,
            accuracy         = xgb_row.mae
        )

    return ForecastResponse(
        symbol            = symbol.upper(),
        prophet_forecasts = prophet_forecasts,
        xgb_signal        = xgb_signal,
        total_days        = len(prophet_forecasts)
    )


@router.post(
    "/{symbol}/run",
    summary="Trigger forecast generation for a stock"
)
def trigger_forecast(
    symbol: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Triggers Prophet + XGBoost forecasting in the background.

    Uses FastAPI BackgroundTasks — returns immediately,
    models train in the background.

    This is also called by the Celery daily task.
    """
    validate_symbol(symbol, db)

    def run_all_models(sym: str):
        from app.ml.forecasting.prophet_model import run_prophet_forecast
        from app.ml.forecasting.xgb_model import run_xgb_forecast

        logger.info(
            "forecast_triggered",
            extra={"symbol": sym}
        )

        prophet_result = run_prophet_forecast(sym)
        xgb_result     = run_xgb_forecast(sym)

        logger.info(
            "forecast_completed",
            extra={
                "symbol":  sym,
                "prophet": prophet_result.get("status"),
                "xgb":     xgb_result.get("status")
            }
        )

    background_tasks.add_task(run_all_models, symbol.upper())

    return {
        "message": f"Forecast triggered for {symbol.upper()}",
        "status":  "running",
        "check":   f"GET /api/forecasts/{symbol.upper()} in 30 seconds"
    }


@router.get(
    "/",
    summary="Get latest forecast signal for all stocks"
)
def get_all_signals(db: Session = Depends(get_db)):
    """
    Returns latest XGBoost signal for all tracked stocks.
    Used by the dashboard overview page.
    """
    from sqlalchemy import func

    # Get latest forecast per symbol
    subq = db.query(
        Forecast.symbol,
        func.max(Forecast.forecast_date).label("max_date")
    ).filter(
        Forecast.model_type == "xgboost"
    ).group_by(Forecast.symbol).subquery()

    rows = db.query(Forecast).join(
        subq,
        (Forecast.symbol == subq.c.symbol) &
        (Forecast.forecast_date == subq.c.max_date)
    ).filter(Forecast.model_type == "xgboost").all()

    signals = []
    for row in rows:
        if row.direction_signal is not None:
            signals.append({
                "symbol":        row.symbol,
                "signal":        "UP" if row.direction_signal == 1 else "DOWN",
                "confidence":    row.confidence,
                "forecast_date": row.forecast_date
            })

    return {"signals": signals, "total": len(signals)}