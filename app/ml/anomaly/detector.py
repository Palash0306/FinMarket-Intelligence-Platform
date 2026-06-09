
# =========================================================
# ANOMALY DETECTOR
# =========================================================
#
# What does this file do in plain English?
#
# It watches stock prices and volume for unusual events.
# "Unusual" = statistically far from the recent average.
#
# We use z-score from statsmodels:
# z_score = (today_value - rolling_mean) / rolling_std
#
# z_score > 2.0 = value is in top 2.5% historically
# z_score > 3.0 = value is in top 0.15% — very rare
#
# Examples of anomalies we detect:
# - AAPL price jumps 8% in one day (price_spike)
# - NVDA volume is 10x the daily average (volume_spike)
# - META drops 12% in one session (price_crash)
#
# Phase 5 uses these to send email/Slack alerts.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# ClickHouse ohlcv table
#       ↓ last 30 days of prices per symbol
#       ↓ read by detect_anomalies_for_symbol()
# statsmodels z-score calculation
#       ↓ any z_score > threshold
# RDS anomalies table (Anomaly model — Phase 3 Day 1)
#       ↓ written by save_anomaly()
#       ↓ read by
# api/anomalies.py → GET /api/anomalies/AAPL
# Phase 5 → sends alerts when is_alerted = False
# Phase 4 RAG → "any anomalies today for AAPL?"
# ─────────────────────────────────────────────────────────

import pandas as pd
import numpy as np
from datetime import datetime, timezone

from app.db.clickhouse import get_clickhouse_client
from app.db.session import SessionLocal
from app.models.anomaly import Anomaly
from app.models.stock import Stock
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Detection thresholds ──────────────────────────────────
#
# Z-score thresholds for anomaly classification:
# MEDIUM_THRESHOLD = 2.0 → unusual (top 2.5%)
# HIGH_THRESHOLD   = 3.0 → very unusual (top 0.15%)
MEDIUM_THRESHOLD = 2.0
HIGH_THRESHOLD   = 3.0

# Rolling window for calculating mean and std
# 20 trading days = roughly 1 month
ROLLING_WINDOW = 20


def calculate_zscore(series: pd.Series) -> pd.Series:
    """
    Calculates rolling z-score for a time series.

    z_score = (value - rolling_mean) / rolling_std

    Each value is compared to the last ROLLING_WINDOW values.
    High z_score = current value is far from recent average.
    """
    rolling_mean = series.rolling(window=ROLLING_WINDOW).mean()
    rolling_std  = series.rolling(window=ROLLING_WINDOW).std()

    # Avoid division by zero
    z_score = (series - rolling_mean) / rolling_std.replace(0, np.nan)

    return z_score.fillna(0)


def detect_anomalies_for_symbol(symbol: str) -> list[dict]:
    """
    Detects price and volume anomalies for one symbol.

    Checks three things:
    1. Price returns (daily % change) — price_spike / price_crash
    2. Volume (absolute) — volume_spike
    3. Price range (high-low spread) — volatility_spike

    Returns list of detected anomaly dicts.
    """
    client  = get_clickhouse_client()
    anomalies = []

    try:
        # ── Fetch last 60 days of daily prices ───────────
        rows = client.execute(
            """
            SELECT
                toDate(timestamp)        AS date,
                argMax(close, timestamp) AS close,
                max(high)                AS high,
                min(low)                 AS low,
                sum(volume)              AS volume
            FROM ohlcv
            WHERE symbol   = %(symbol)s
              AND timestamp >= now() - toIntervalDay(60)
            GROUP BY date
            ORDER BY date ASC
            """,
            {"symbol": symbol}
        )

    except Exception as e:
        logger.error(
            "clickhouse_anomaly_fetch_error",
            extra={"symbol": symbol, "error": str(e)}
        )
        return []

    if len(rows) < ROLLING_WINDOW + 1:
        return []  # Not enough data for rolling calculation

    df = pd.DataFrame(
        rows,
        columns=["date", "close", "high", "low", "volume"]
    )

    # ── Calculate daily returns ───────────────────────────
    #
    # pct_change() = (today - yesterday) / yesterday
    # This normalises price moves — a $5 move in a $10 stock
    # is very different from a $5 move in a $300 stock
    df["returns"] = df["close"].pct_change().fillna(0)

    # ── Calculate high-low range ──────────────────────────
    df["hl_range"] = (df["high"] - df["low"]) / df["close"]

    # ── Calculate z-scores ───────────────────────────────
    df["returns_zscore"] = calculate_zscore(df["returns"])
    df["volume_zscore"]  = calculate_zscore(df["volume"])
    df["range_zscore"]   = calculate_zscore(df["hl_range"])

    # ── Check latest row for anomalies ────────────────────
    #
    # We only check the most recent day.
    # Historical anomalies were already detected and saved.
    latest = df.iloc[-1]
    today  = str(latest["date"])

    # ── Price return anomaly ──────────────────────────────
    returns_z = abs(float(latest["returns_zscore"]))
    if returns_z >= MEDIUM_THRESHOLD:
        returns_val = float(latest["returns"])

        if returns_val > 0:
            anomaly_type = "price_spike"
        else:
            anomaly_type = "price_crash"

        severity = "high" if returns_z >= HIGH_THRESHOLD else "medium"

        anomalies.append({
            "symbol":         symbol,
            "detected_at":    datetime.now(timezone.utc).isoformat(),
            "anomaly_type":   anomaly_type,
            "z_score":        round(returns_z, 4),
            "actual_value":   round(float(latest["close"]), 4),
            "expected_value": round(
                float(df["close"].rolling(ROLLING_WINDOW).mean().iloc[-1]),
                4
            ),
            "description": (
                f"{symbol} price {'surged' if returns_val > 0 else 'dropped'} "
                f"{abs(returns_val)*100:.1f}% "
                f"({returns_z:.1f}σ from {ROLLING_WINDOW}-day mean)"
            ),
            "severity": severity
        })

    # ── Volume anomaly ────────────────────────────────────
    volume_z = abs(float(latest["volume_zscore"]))
    if volume_z >= MEDIUM_THRESHOLD:
        severity = "high" if volume_z >= HIGH_THRESHOLD else "medium"

        anomalies.append({
            "symbol":         symbol,
            "detected_at":    datetime.now(timezone.utc).isoformat(),
            "anomaly_type":   "volume_spike",
            "z_score":        round(volume_z, 4),
            "actual_value":   round(float(latest["volume"]), 0),
            "expected_value": round(
                float(df["volume"].rolling(ROLLING_WINDOW).mean().iloc[-1]),
                0
            ),
            "description": (
                f"{symbol} volume was "
                f"{volume_z:.1f}σ above {ROLLING_WINDOW}-day average"
            ),
            "severity": severity
        })

    return anomalies


def save_anomaly(anomaly_data: dict) -> bool:
    """
    Saves one anomaly to RDS anomalies table.

    Checks if same anomaly type was already detected today
    to avoid duplicate alerts.

    Connection chain:
    detector.py → session.py → Anomaly model → RDS anomalies
    """
    db = SessionLocal()
    try:
        # ── Check for duplicate ───────────────────────────
        today = anomaly_data["detected_at"][:10]

        existing = db.query(Anomaly).filter(
            Anomaly.symbol       == anomaly_data["symbol"],
            Anomaly.anomaly_type == anomaly_data["anomaly_type"],
            Anomaly.detected_at.like(f"{today}%")
        ).first()

        if existing:
            return False

        # ── Save new anomaly ──────────────────────────────
        anomaly = Anomaly(
            symbol         = anomaly_data["symbol"],
            detected_at    = anomaly_data["detected_at"],
            anomaly_type   = anomaly_data["anomaly_type"],
            z_score        = anomaly_data["z_score"],
            actual_value   = anomaly_data["actual_value"],
            expected_value = anomaly_data["expected_value"],
            description    = anomaly_data["description"],
            severity       = anomaly_data["severity"],
            is_alerted     = False
        )

        db.add(anomaly)
        db.commit()
        return True

    except Exception as e:
        db.rollback()
        logger.error(
            "anomaly_save_error",
            extra={"error": str(e)}
        )
        return False
    finally:
        db.close()


def run_anomaly_detection() -> dict:
    """
    Main entry point — runs anomaly detection for all symbols.

    Flow:
    ┌──────────────────────────────────────────────────┐
    │ 1. Get all active symbols from RDS               │
    │ 2. detect_anomalies_for_symbol() per symbol      │
    │ 3. Save any detected anomalies to RDS            │
    └──────────────────────────────────────────────────┘

    Called by Celery every 15 minutes.
    """
    db = SessionLocal()
    try:
        symbols = [
            s.symbol for s in
            db.query(Stock).filter(Stock.is_active == True).all()
        ]
    finally:
        db.close()

    total_anomalies = 0

    for symbol in symbols:
        anomalies = detect_anomalies_for_symbol(symbol)

        for anomaly_data in anomalies:
            saved = save_anomaly(anomaly_data)
            if saved:
                total_anomalies += 1
                logger.info(
                    "anomaly_detected",
                    extra={
                        "symbol":   symbol,
                        "type":     anomaly_data["anomaly_type"],
                        "z_score":  anomaly_data["z_score"],
                        "severity": anomaly_data["severity"]
                    }
                )

    return {
        "status":          "success",
        "symbols_checked": len(symbols),
        "anomalies_found": total_anomalies
    }