# =========================================================
# FORECAST SCHEMAS
# =========================================================
#
# Defines the shape of forecast data returned by the API.
#
# Connection chain:
# RDS forecasts table (Forecast model)
#       ↓ queried by
# api/forecasts.py
#       ↓ shaped by
# THESE SCHEMAS
#       ↓ returned to
# Browser / Streamlit dashboard (Phase 5)
# Phase 4 RAG agent

from pydantic import BaseModel, Field
from typing import Optional


class ProphetForecastPoint(BaseModel):
    """One day's Prophet forecast."""
    forecast_date:   str
    predicted_price: float
    lower_bound:     float
    upper_bound:     float
    mae:             Optional[float] = None

    model_config = {"from_attributes": True}


class XGBSignalResponse(BaseModel):
    """XGBoost direction signal for tomorrow."""
    symbol:           str
    forecast_date:    str
    direction_signal: int   # 1=UP, 0=DOWN
    signal_label:     str   # "UP" or "DOWN"
    confidence:       float # 0.0 to 1.0
    accuracy:         Optional[float] = None

    model_config = {"from_attributes": True}


class ForecastResponse(BaseModel):
    """
    Combined forecast response for one symbol.
    Includes both Prophet price forecast and XGBoost signal.
    """
    symbol:          str
    prophet_forecasts: list[ProphetForecastPoint]
    xgb_signal:      Optional[XGBSignalResponse] = None
    total_days:      int