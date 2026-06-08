# =========================================================
# XGBOOST BUY/SELL SIGNAL CLASSIFIER
# =========================================================
#
# What is XGBoost in plain English?
#
# XGBoost is a decision tree ensemble — it builds many
# simple decision trees and combines them into one powerful
# predictor. It learns from features (RSI, MACD, etc.)
# to predict whether a stock will go UP or DOWN tomorrow.
#
# This is a CLASSIFICATION task:
# Input:  today's RSI, MACD, Bollinger position, volume...
# Output: 1 (UP tomorrow) or 0 (DOWN tomorrow)
#
# Important disclaimer:
# Stock prediction is extremely difficult. This model
# gives a signal, not a guarantee. It learns historical
# patterns — but markets can change. Use as one signal
# among many, not as financial advice.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# ClickHouse ohlcv
#       ↓ prices fetched by
# get_price_history_from_clickhouse() (reused from prophet_model.py)
#       ↓ features built by
# feature_engineering.build_feature_dataframe() (Phase 3 Day 1)
#       ↓
# XGBoost trains on features
#       ↓ predicts UP/DOWN signal
# RDS forecasts table (direction_signal, confidence columns)
#       ↓ logged to
# MLflow (experiment: xgb_{symbol})
#       ↓ read by
# api/forecasts.py → GET /api/forecasts/AAPL/signal
# Phase 5 dashboard → signal indicator
# ─────────────────────────────────────────────────────────

import pandas as pd
import numpy as np
from datetime import datetime

import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score

from app.ml.forecasting.prophet_model import (
    get_price_history_from_clickhouse
)
from app.ml.utils.feature_engineering import build_feature_dataframe
from app.db.session import SessionLocal
from app.models.forecast import Forecast
from app.ml.utils.mlflow_helper import log_model_run
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Model configuration ───────────────────────────────────
#
# These hyperparameters control XGBoost's behaviour.
# They are reasonable defaults — Phase 3 Day 3 will add
# proper hyperparameter tuning with cross-validation.
XGB_PARAMS = {
    "n_estimators":  100,  # number of trees to build
    "max_depth":     4,    # max depth per tree (prevents overfitting)
    "learning_rate": 0.1,  # how much each tree contributes
    "subsample":     0.8,  # fraction of data per tree (prevents overfitting)
    "random_state":  42    # reproducibility
}

MIN_SAMPLES = 50  # minimum rows needed to train


def create_target_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Creates the binary target variable for classification.

    Target = 1 if tomorrow's close > today's close (price UP)
    Target = 0 if tomorrow's close <= today's close (price DOWN)

    This is called a 'forward return' label — we shift prices
    by -1 to align tomorrow's return with today's features.

    Example:
    Date    Close  tomorrow_close  target
    Jan 1   100    105             1 (UP)
    Jan 2   105    98              0 (DOWN)
    Jan 3   98     ...             1 (UP)

    The last row is dropped because we don't know tomorrow's price.
    """
    df = df.copy()

    # Shift close by -1 to get tomorrow's price in today's row
    df["tomorrow_close"] = df["close"].shift(-1)

    # 1 = price goes up, 0 = price goes down or stays same
    df["target"] = (
        df["tomorrow_close"] > df["close"]
    ).astype(int)

    # Drop last row — no tomorrow yet
    df = df.dropna(subset=["tomorrow_close"])

    return df


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """
    Returns the list of feature columns to use for training.

    We exclude non-feature columns:
    - timestamp: not a feature (would cause data leakage)
    - close, open, high, low, volume: raw prices
    - target: this is what we are predicting
    - tomorrow_close: this leaks future data
    """
    exclude = {
        "timestamp", "date","ds", "close", "open", "high",
        "low", "volume", "target", "tomorrow_close"
    }
    return [col for col in df.columns if col not in exclude]


def train_xgb_model(
    symbol: str,
    df: pd.DataFrame
) -> tuple:
    """
    Trains XGBoost classifier on feature data.

    Returns:
        model:      trained XGBoost classifier
        accuracy:   % of correct predictions on test set
        precision:  % of 'UP' predictions that were actually UP
        features:   list of feature column names used

    Train/test split:
    80% of data for training, 20% for testing.
    shuffle=False because this is time-series — we must
    test on the MOST RECENT data, not random samples.
    Shuffling would cause data leakage (training on future data).
    """

    # ── Create labels ─────────────────────────────────────
    df = create_target_labels(df)

    if len(df) < MIN_SAMPLES:
        raise ValueError(
            f"Need {MIN_SAMPLES} samples, have {len(df)}"
        )

    feature_cols = get_feature_columns(df)

    # ── Split features and target ─────────────────────────
    X = df[feature_cols]
    y = df["target"]

    # ── Time-series split (NO shuffle) ───────────────────
    #
    # shuffle=False is critical for time-series.
    # test_size=0.2 = last 20% of data is test set
    # This simulates real-world: train on past, predict future
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=0.2,
        shuffle=False  # ← never shuffle time-series
    )

    # ── Train XGBoost ─────────────────────────────────────
    model = xgb.XGBClassifier(
        **XGB_PARAMS,
        eval_metric="logloss",
        use_label_encoder=False
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        verbose=False
    )

    # ── Evaluate on test set ──────────────────────────────
    y_pred     = model.predict(X_test)
    accuracy   = round(float(accuracy_score(y_test, y_pred)), 4)

    # Precision: of all times we said UP, how often was it UP?
    precision  = round(
        float(precision_score(y_test, y_pred, zero_division=0)),
        4
    )

    logger.info(
        "xgb_trained",
        extra={
            "symbol":    symbol,
            "accuracy":  accuracy,
            "precision": precision,
            "train_rows": len(X_train),
            "test_rows":  len(X_test),
            "features":   len(feature_cols)
        }
    )

    return model, accuracy, precision, feature_cols


def predict_next_day_signal(
    model: xgb.XGBClassifier,
    df: pd.DataFrame,
    feature_cols: list[str]
) -> tuple[int, float]:
    """
    Predicts tomorrow's direction using today's features.

    Takes the LAST ROW of features (most recent day)
    and asks: will price go up or down tomorrow?

    Returns:
        signal:     1 = UP, 0 = DOWN
        confidence: probability of the predicted direction (0-1)
    """
    # Get the most recent row of features
    latest_features = df[feature_cols].iloc[-1:]

    # predict() returns [0] or [1]
    signal = int(model.predict(latest_features)[0])

    # predict_proba() returns [[prob_down, prob_up]]
    # We take the probability of the predicted class
    proba      = model.predict_proba(latest_features)[0]
    confidence = round(float(proba[signal]), 4)

    return signal, confidence


def save_signal_to_rds(
    symbol: str,
    signal: int,
    confidence: float,
    accuracy: float
) -> None:
    """
    Saves XGBoost signal to RDS forecasts table.

    Creates one row for tomorrow's date with:
    direction_signal: 1 (UP) or 0 (DOWN)
    confidence:       model's certainty
    mae:              accuracy on test set (stored for comparison)
    model_type:       "xgboost"

    Connection chain:
    This function → session.py → Forecast model → RDS forecasts table
    """
    from datetime import timedelta
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        existing = db.query(Forecast).filter(
            Forecast.symbol        == symbol,
            Forecast.forecast_date == tomorrow,
            Forecast.model_type    == "xgboost"
        ).first()

        if existing:
            existing.direction_signal = signal
            existing.confidence       = confidence
            existing.mae              = accuracy
        else:
            forecast = Forecast(
                symbol           = symbol,
                forecast_date    = tomorrow,
                model_type       = "xgboost",
                direction_signal = signal,
                confidence       = confidence,
                mae              = accuracy
            )
            db.add(forecast)

        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(
            "signal_save_error",
            extra={"symbol": symbol, "error": str(e)}
        )
    finally:
        db.close()


def run_xgb_forecast(symbol: str) -> dict:
    """
    Main entry point — trains XGBoost and saves signal.

    Full flow:
    ┌──────────────────────────────────────────────────┐
    │ 1. Fetch 90 days of prices from ClickHouse       │
    │ 2. Build feature DataFrame (RSI, MACD, BB, etc.) │
    │ 3. Create binary target labels (UP/DOWN)         │
    │ 4. Train XGBoost with time-series split          │
    │ 5. Predict tomorrow's direction signal           │
    │ 6. Log to MLflow                                 │
    │ 7. Save signal to RDS forecasts table            │
    └──────────────────────────────────────────────────┘
    """
    logger.info(
        "xgb_forecast_started",
        extra={"symbol": symbol}
    )

    # ── Step 1: Fetch prices ──────────────────────────────
    df_raw = get_price_history_from_clickhouse(symbol, days=250)

    if df_raw.empty:
        return {"symbol": symbol, "status": "no_data"}

    # ── Step 2: Build features ────────────────────────────
    #
    # feature_engineering.py from Phase 3 Day 1
    # Adds RSI, MACD, Bollinger Bands, returns, etc.
    df_features = build_feature_dataframe(symbol, df_raw)

    if df_features.empty or len(df_features) < MIN_SAMPLES:
        return {
            "symbol": symbol,
            "status": "insufficient_features",
            "rows":   len(df_features)
        }

    # ── Step 3 + 4: Train model ───────────────────────────
    try:
        model, accuracy, precision, feature_cols = train_xgb_model(
            symbol, df_features
        )
    except Exception as e:
        logger.error(
            "xgb_training_error",
            extra={"symbol": symbol, "error": str(e)}
        )
        return {"symbol": symbol, "status": "error", "error": str(e)}

    # ── Step 5: Predict tomorrow ──────────────────────────
    signal, confidence = predict_next_day_signal(
        model, df_features, feature_cols
    )

    signal_label = "UP" if signal == 1 else "DOWN"

    # ── Step 6: Log to MLflow ─────────────────────────────
    try:
        run_id = log_model_run(
            experiment_name = f"xgb_{symbol}",
            run_name        = datetime.now().strftime("%Y%m%d_%H%M"),
            params          = {
                "symbol":        symbol,
                **XGB_PARAMS,
                "features_used": len(feature_cols)
            },
            metrics = {
                "accuracy":   accuracy,
                "precision":  precision,
                "confidence": confidence,
                "signal":     signal
            },
            model      = model,
            model_type = "xgboost"
        )
    except Exception as e:
        logger.warning(f"mlflow_log_failed: {e}")
        run_id = "mlflow_unavailable"

    # ── Step 7: Save to RDS ───────────────────────────────
    save_signal_to_rds(symbol, signal, confidence, accuracy)

    result = {
        "symbol":        symbol,
        "status":        "success",
        "signal":        signal_label,
        "confidence":    confidence,
        "accuracy":      accuracy,
        "precision":     precision,
        "mlflow_run_id": run_id
    }

    logger.info("xgb_forecast_completed", extra=result)
    return result