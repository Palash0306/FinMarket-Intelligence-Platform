# =========================================================
# PROPHET PRICE FORECASTING MODEL
# =========================================================
#
# What is Prophet in plain English?
#
# Prophet is a forecasting tool built by Facebook/Meta.
# You give it historical data with dates and values,
# it learns the patterns (trends, weekly cycles, seasonality)
# and predicts future values.
#
# Think of it like a weather forecast — it does not know
# exactly what will happen, but based on patterns it gives
# you a range of likely outcomes with confidence intervals.
#
# Why Prophet for stock prices?
# - Handles missing data well (weekends, holidays)
# - Automatically detects weekly patterns
# - Gives confidence intervals (not just point estimates)
# - Fast to train even with years of data
# - Free, runs locally — no GPU needed
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# ClickHouse ohlcv table
#       ↓ 90 days of daily prices fetched by
# get_price_history_from_clickhouse()
#       ↓ passed through
# feature_engineering.py (for XGBoost later)
# Prophet uses RAW prices directly (not features)
#       ↓ Prophet trains and forecasts
# forecast results saved to
# RDS forecasts table (Forecast model — Phase 3 Day 1)
#       ↓ logged to
# MLflow (mlflow_helper.py — Phase 3 Day 1)
#       ↓ read by
# api/forecasts.py → GET /api/forecasts/AAPL
# Phase 4 RAG agent
# Phase 5 Streamlit dashboard
# ─────────────────────────────────────────────────────────

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from prophet import Prophet

from app.db.clickhouse import get_clickhouse_client
from app.db.session import SessionLocal
from app.models.forecast import Forecast
from app.ml.utils.mlflow_helper import log_model_run
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Forecast horizon ──────────────────────────────────────
#
# How many days ahead to forecast.
# 7 = one week ahead — reasonable for financial forecasting.
# Longer horizons = less accurate. 30+ days = very uncertain.
FORECAST_DAYS = 7

# ── Minimum data requirement ──────────────────────────────
#
# Prophet needs enough historical data to learn patterns.
# 30 days minimum. More = better (we use 90).
MIN_DATA_POINTS = 30


def get_price_history_from_clickhouse(
    symbol: str,
    days: int = 90
) -> pd.DataFrame:
    """
    Fetches historical daily prices from ClickHouse.

    We aggregate 5-minute candles to daily OHLCV.
    Prophet needs daily data — not 5-minute intervals.

    Connection chain:
    ClickHouse ohlcv table (written by price_consumer.py)
        ↓ aggregate to daily with ClickHouse SQL
        ↓ return as pandas DataFrame
    prophet_train() uses this DataFrame

    Returns DataFrame with columns: ds, y
    (Prophet requires these exact column names)
    ds = date stamp (Prophet's required name)
    y  = value to forecast (Prophet's required name)
    """
    client = get_clickhouse_client()

    try:
        # ── Aggregate 5-min candles to daily ─────────────
        #
        # toDate() strips time from timestamp → groups by day
        # argMax(close, timestamp) = closing price at end of day
        # We only need daily data for Prophet
        rows = client.execute(
            """
            SELECT
                toDate(timestamp)        AS date,
                argMin(open, timestamp)  AS open,
                max(high)                AS high,
                min(low)                 AS low,
                argMax(close, timestamp) AS close,
                sum(volume)              AS volume
            FROM ohlcv
            WHERE symbol = %(symbol)s
              AND timestamp >= now() - toIntervalDay(%(days)s)
            GROUP BY date
            ORDER BY date ASC
            """,
            {"symbol": symbol, "days": days}
        )

    except Exception as e:
        logger.error(
            "clickhouse_fetch_error",
            extra={"symbol": symbol, "error": str(e)}
        )
        return pd.DataFrame()

    if not rows:
        logger.warning(
            "no_price_history",
            extra={"symbol": symbol}
        )
        return pd.DataFrame()

    # ── Convert to DataFrame ──────────────────────────────
    df = pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close", "volume"]
    )

    # ── Rename columns for Prophet ────────────────────────
    #
    # Prophet REQUIRES columns named 'ds' and 'y'.
    # ds = date (datetime column)
    # y  = the value we are forecasting (close price)
    df["ds"] = pd.to_datetime(df["date"])
    df["y"]  = df["close"].astype(float)

    logger.info(
        "price_history_fetched",
        extra={"symbol": symbol, "rows": len(df)}
    )

    return df[["ds", "y", "date", "open", "high", "low", "close", "volume"]]


def train_prophet_model(
    symbol: str,
    df: pd.DataFrame
) -> tuple[Prophet, pd.DataFrame]:
    """
    Trains a Prophet model on historical price data.

    What Prophet learns:
    - Overall trend (is price generally going up or down?)
    - Weekly seasonality (do prices behave differently Mon vs Fri?)
    - Changepoints (where did the trend shift suddenly?)

    Prophet params explained:
    changepoint_prior_scale=0.05:
        How flexible the trend line is. Higher = follows data
        more closely but risks overfitting. 0.05 is conservative.
    weekly_seasonality=True:
        Stock prices have weekly patterns (Mon dip, Fri rally etc.)
    daily_seasonality=False:
        We have daily data, not intraday, so no sub-daily patterns.
    interval_width=0.80:
        80% confidence interval. Model is 80% confident actual
        price falls between lower_bound and upper_bound.

    Returns:
        model:    trained Prophet object
        forecast: DataFrame with predictions (yhat, yhat_lower, yhat_upper)
    """

    # ── Train Prophet ─────────────────────────────────────
    #
    # Prophet works like scikit-learn:
    # model.fit(data) → model.predict(future_dates)
    model = Prophet(
        changepoint_prior_scale=0.05,
        weekly_seasonality=True,
        daily_seasonality=False,
        interval_width=0.80,
        # Suppress verbose Stan/cmdstanpy output
        # Stan is the Bayesian inference library Prophet uses
        stan_backend="CMDSTANPY"
    )

    # Suppress stdout during training
    import logging as py_logging
    py_logging.getLogger("prophet").setLevel(py_logging.WARNING)
    py_logging.getLogger("cmdstanpy").setLevel(py_logging.WARNING)

    # ── Fit on historical data ────────────────────────────
    # df must have columns 'ds' (date) and 'y' (value)
    model.fit(df[["ds", "y"]])

    # ── Create future date range ──────────────────────────
    #
    # make_future_dataframe creates a DataFrame of dates.
    # include_history=True = includes training dates too.
    # We use include_history=False to get only future dates.
    future = model.make_future_dataframe(
        periods=FORECAST_DAYS,
        freq="D",              # D = daily frequency
        include_history=False  # only future dates
    )

    # ── Generate predictions ──────────────────────────────
    #
    # forecast contains:
    # ds          = date
    # yhat        = predicted price (the main forecast)
    # yhat_lower  = lower confidence bound (80%)
    # yhat_upper  = upper confidence bound (80%)
    forecast = model.predict(future)

    return model, forecast


def calculate_mae(actual: pd.Series, predicted: pd.Series) -> float:
    """
    Mean Absolute Error — how wrong the model is on average.

    MAE = average of |actual - predicted| across all data points.

    Example:
    actual = [100, 105, 98]
    predicted = [102, 103, 99]
    errors = [2, 2, 1]
    MAE = 1.67

    Lower is better. We log this to MLflow for comparison.
    """
    if len(actual) == 0 or len(predicted) == 0:
        return 0.0

    # Align the series by index
    min_len = min(len(actual), len(predicted))
    errors  = abs(actual.values[:min_len] - predicted.values[:min_len])
    return round(float(errors.mean()), 4)


def save_forecasts_to_rds(
    symbol: str,
    forecast_df: pd.DataFrame,
    mae: float
) -> int:
    """
    Saves Prophet forecast results to RDS forecasts table.

    One row per forecast date. FORECAST_DAYS rows total per run.
    Uses upsert logic — if forecast for that date already exists
    (from a previous run today), skip it.

    Connection chain:
    Prophet forecast DataFrame
        ↓ this function
        ↓ uses session.py + Forecast model (Phase 3 Day 1)
    RDS forecasts table
    """
    db = SessionLocal()
    saved = 0

    try:
        for _, row in forecast_df.iterrows():
            forecast_date = str(row["ds"])[:10]  # YYYY-MM-DD

            # ── Check for existing forecast ───────────────
            existing = db.query(Forecast).filter(
                Forecast.symbol      == symbol,
                Forecast.forecast_date == forecast_date,
                Forecast.model_type  == "prophet"
            ).first()

            if existing:
                # Update existing forecast
                existing.predicted_price = round(float(row["yhat"]), 4)
                existing.lower_bound     = round(float(row["yhat_lower"]), 4)
                existing.upper_bound     = round(float(row["yhat_upper"]), 4)
                existing.mae             = mae
            else:
                # Create new forecast row
                forecast = Forecast(
                    symbol          = symbol,
                    forecast_date   = forecast_date,
                    model_type      = "prophet",
                    predicted_price = round(float(row["yhat"]), 4),
                    lower_bound     = round(float(row["yhat_lower"]), 4),
                    upper_bound     = round(float(row["yhat_upper"]), 4),
                    mae             = mae
                )
                db.add(forecast)
                saved += 1

        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(
            "forecast_save_error",
            extra={"symbol": symbol, "error": str(e)}
        )
    finally:
        db.close()

    return saved


def run_prophet_forecast(symbol: str) -> dict:
    """
    Main entry point — trains Prophet and saves forecasts.

    Full flow:
    ┌──────────────────────────────────────────────────┐
    │ 1. Fetch 90 days of prices from ClickHouse       │
    │ 2. Check we have enough data (MIN_DATA_POINTS)   │
    │ 3. Train Prophet model                           │
    │ 4. Generate 7-day forecast                       │
    │ 5. Calculate MAE on training data                │
    │ 6. Log run to MLflow (params + metrics + model)  │
    │ 7. Save forecasts to RDS forecasts table         │
    └──────────────────────────────────────────────────┘

    Returns dict with summary for Celery task logging.
    """
    logger.info(
        "prophet_forecast_started",
        extra={"symbol": symbol}
    )

    # ── Step 1: Get price history ─────────────────────────
    df = get_price_history_from_clickhouse(symbol, days=90)

    if df.empty or len(df) < MIN_DATA_POINTS:
        logger.warning(
            "insufficient_data",
            extra={
                "symbol": symbol,
                "rows": len(df),
                "required": MIN_DATA_POINTS
            }
        )
        return {
            "symbol": symbol,
            "status": "skipped",
            "reason": f"need {MIN_DATA_POINTS} days, have {len(df)}"
        }

    # ── Step 2: Train model ───────────────────────────────
    try:
        model, forecast = train_prophet_model(symbol, df)
    except Exception as e:
        logger.error(
            "prophet_training_error",
            extra={"symbol": symbol, "error": str(e)}
        )
        return {"symbol": symbol, "status": "error", "error": str(e)}

    # ── Step 3: Calculate MAE on in-sample data ───────────
    #
    # Get Prophet's fit on historical data for MAE calculation
    historical_forecast = model.predict(df[["ds"]])
    mae = calculate_mae(df["y"], historical_forecast["yhat"])

    # ── Step 4: Log to MLflow ─────────────────────────────
    try:
        run_id = log_model_run(
            experiment_name = f"prophet_{symbol}",
            run_name        = datetime.now().strftime("%Y%m%d_%H%M"),
            params={
                "symbol":                   symbol,
                "changepoint_prior_scale":  0.05,
                "forecast_days":            FORECAST_DAYS,
                "training_days":            len(df),
                "interval_width":           0.80
            },
            metrics={
                "mae":          mae,
                "training_rows": len(df),
                "forecast_rows": len(forecast)
            },
            model      = model,
            model_type = "sklearn"
        )
    except Exception as e:
        logger.warning(f"mlflow_log_failed: {e}")
        run_id = "mlflow_unavailable"

    # ── Step 5: Save to RDS ───────────────────────────────
    saved = save_forecasts_to_rds(symbol, forecast, mae)

    result = {
        "symbol":        symbol,
        "status":        "success",
        "forecast_days": len(forecast),
        "saved_rows":    saved,
        "mae":           mae,
        "mlflow_run_id": run_id
    }

    logger.info(
        "prophet_forecast_completed",
        extra=result
    )

    return result