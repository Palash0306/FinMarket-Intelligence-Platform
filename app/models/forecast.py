# path: app/models/forecast.py

# =========================================================
# FORECAST MODEL
# =========================================================
#
# Stores ML model predictions for stock prices.
# One row = one price forecast for one symbol for one date.
#
# Connection chain:
# ClickHouse ohlcv (prices)
#       ↓ read by
# prophet_model.py + xgb_model.py
#       ↓ predictions stored in
# THIS TABLE (forecasts)
#       ↓ read by
# api/forecasts.py → GET /api/forecasts/AAPL
# Phase 5 dashboard → forecast chart
# Phase 4 RAG agent → "what is AAPL forecast?"
#
# Two model types stored here:
# prophet  → continuous price prediction (float)
# xgboost  → direction signal (1=up, 0=down, -1=unknown)

from sqlalchemy import Integer, String, Float, Date, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Forecast(Base, TimestampMixin):
    """
    One price forecast for one symbol on one date.

    Table: forecasts
    """

    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    # Which stock this forecast is for
    symbol: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="Stock ticker symbol"
    )

    # Which date this forecast is predicting
    # e.g. today we predict price for tomorrow
    forecast_date: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Date being forecast: YYYY-MM-DD"
    )

    # Which ML model made this prediction
    # "prophet" or "xgboost"
    model_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Model: prophet or xgboost"
    )

    # ── Prophet outputs ───────────────────────────────────
    #
    # predicted_price: the forecasted closing price
    # lower_bound:     lower confidence interval (80%)
    # upper_bound:     upper confidence interval (80%)
    # These three define the "cone of uncertainty"
    predicted_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Predicted closing price from Prophet"
    )

    lower_bound: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Lower 80% confidence interval"
    )

    upper_bound: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Upper 80% confidence interval"
    )

    # ── XGBoost outputs ───────────────────────────────────
    #
    # direction_signal: 1 = price predicted to go UP
    #                   0 = price predicted to go DOWN
    # confidence:       how confident the model is (0-1)
    direction_signal: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="1=up 0=down — XGBoost direction prediction"
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Model confidence 0.0 to 1.0"
    )

    # Model performance metrics — logged by MLflow
    # Stored here for quick API access
    mae: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Mean Absolute Error of this model run"
    )

    __table_args__ = (
        Index(
            "ix_forecast_symbol_date",
            "symbol",
            "forecast_date",
            "model_type"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Forecast {self.symbol} "
            f"{self.forecast_date} "
            f"{self.model_type}: {self.predicted_price}>"
        )