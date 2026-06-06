# path: app/ml/utils/feature_engineering.py

# =========================================================
# FEATURE ENGINEERING
# =========================================================
#
# What is feature engineering in plain English?
#
# Raw price data looks like:
# Date       Close
# 2024-01-01 182.50
# 2024-01-02 183.20
# ...
#
# ML models can not learn much from raw prices alone.
# They need CONTEXT — how is this price compared to
# its recent history? Is it trending up? Is volume high?
#
# Feature engineering extracts that context:
# Date       Close  RSI    MACD   Volume_ZScore  Returns_5d
# 2024-01-01 182.50 65.3   0.42   1.2            0.032
# 2024-01-02 183.20 67.1   0.55   0.8            0.035
#
# These features are what XGBoost actually learns from.
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# ClickHouse ohlcv table
#       ↓ raw price data
# THIS FILE (feature_engineering.py)
#       ↓ calculates RSI, MACD, Bollinger Bands etc.
#       ↓ returns ML-ready DataFrame
# xgb_model.py ──────── uses features for classification
# prophet_model.py ───── uses raw prices (not features)
# detector.py ─────────  uses z-score features for anomalies
# ─────────────────────────────────────────────────────────

import pandas as pd
import numpy as np
from app.utils.logger import get_logger

logger = get_logger(__name__)


def calculate_rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    """
    Relative Strength Index (RSI).

    What it measures in plain English:
    How "overbought" or "oversold" a stock is.

    Range: 0 to 100
    > 70 = overbought (price may be too high, could drop)
    < 30 = oversold (price may be too low, could rise)
    50   = neutral

    Formula:
    RSI = 100 - (100 / (1 + avg_gain / avg_loss))
    over a rolling 14-day window.

    Why 14 days? Industry standard — works well empirically.
    """
    # Calculate daily price changes
    delta = prices.diff()

    # Separate gains (positive changes) and losses (negative)
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)

    # Rolling exponential average of gains and losses
    # ewm = exponentially weighted mean (recent data weighted more)
    avg_gain = gains.ewm(com=window - 1, min_periods=window).mean()
    avg_loss = losses.ewm(com=window - 1, min_periods=window).mean()

    # Relative strength ratio
    rs = avg_gain / avg_loss.replace(0, np.nan)

    # Convert to 0-100 scale
    rsi = 100 - (100 / (1 + rs))

    return rsi.fillna(50)  # fill NaN with neutral value


def calculate_macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD — Moving Average Convergence Divergence.

    What it measures in plain English:
    The relationship between two moving averages.
    Tells you whether momentum is increasing or decreasing.

    Three components:
    macd_line   = fast EMA (12-day) - slow EMA (26-day)
    signal_line = 9-day EMA of macd_line
    histogram   = macd_line - signal_line

    Trading signals:
    macd_line crosses above signal_line → bullish
    macd_line crosses below signal_line → bearish
    """
    # Exponential moving averages
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()

    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_bollinger_bands(
    prices: pd.Series,
    window: int = 20,
    num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.

    What they measure in plain English:
    A price "envelope" showing normal range of movement.

    Three lines:
    middle = 20-day rolling average
    upper  = middle + 2 standard deviations
    lower  = middle - 2 standard deviations

    When price touches upper band → potentially overbought
    When price touches lower band → potentially oversold
    When bands narrow → low volatility (breakout coming?)
    """
    middle = prices.rolling(window=window).mean()
    std    = prices.rolling(window=window).std()

    upper = middle + (num_std * std)
    lower = middle - (num_std * std)

    return upper, middle, lower


def calculate_volume_zscore(
    volume: pd.Series,
    window: int = 20
) -> pd.Series:
    """
    Volume Z-Score.

    What it measures in plain English:
    How unusual today's trading volume is compared
    to the last 20 days.

    z_score = (today_volume - avg_volume) / std_volume

    z_score > 2.0 = unusually high volume
    z_score < -2.0 = unusually low volume
    z_score ≈ 0.0 = normal volume

    High volume during a price move = strong signal
    High volume but no price move = potential reversal
    """
    rolling_mean = volume.rolling(window=window).mean()
    rolling_std  = volume.rolling(window=window).std()

    z_score = (volume - rolling_mean) / rolling_std.replace(0, 1)

    return z_score.fillna(0)


def calculate_returns(
    prices: pd.Series,
    periods: list[int] = [1, 5, 10, 20]
) -> dict[str, pd.Series]:
    """
    Percentage returns over multiple time windows.

    What they measure in plain English:
    How much the price has changed over the last N days.

    returns_1d  = change since yesterday
    returns_5d  = change over last week
    returns_10d = change over last 2 weeks
    returns_20d = change over last month

    These tell the model about momentum and trend direction.
    """
    returns = {}
    for period in periods:
        col_name = f"returns_{period}d"
        returns[col_name] = prices.pct_change(periods=period).fillna(0)
    return returns


def build_feature_dataframe(
    symbol: str,
    prices_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Main function — builds complete ML feature set.

    Takes raw OHLCV DataFrame from ClickHouse and returns
    a feature-rich DataFrame ready for XGBoost.

    Input (from ClickHouse):
        timestamp | open | high | low | close | volume

    Output (ML-ready):
        timestamp | close | rsi | macd | macd_signal |
        bb_upper | bb_middle | bb_lower | volume_zscore |
        returns_1d | returns_5d | returns_10d | returns_20d |
        high_low_ratio | close_open_ratio | price_position

    Connection chain:
    ClickHouse ohlcv ──→ this function ──→ xgb_model.py
    """
    if prices_df.empty:
        logger.warning(
            "empty_dataframe",
            extra={"symbol": symbol}
        )
        return pd.DataFrame()

    df = prices_df.copy()

    # Sort by time — essential for rolling calculations
    df = df.sort_values("timestamp").reset_index(drop=True)

    close  = df["close"]
    volume = df["volume"]

    # ── RSI ───────────────────────────────────────────────
    df["rsi"] = calculate_rsi(close)

    # ── MACD ─────────────────────────────────────────────
    df["macd"], df["macd_signal"], df["macd_hist"] = (
        calculate_macd(close)
    )

    # ── Bollinger Bands ───────────────────────────────────
    df["bb_upper"], df["bb_middle"], df["bb_lower"] = (
        calculate_bollinger_bands(close)
    )

    # ── Bollinger Band position ───────────────────────────
    #
    # Where is the current price within the bands?
    # 0.0 = at lower band, 1.0 = at upper band, 0.5 = middle
    # This tells the model if price is stretched
    bb_range = df["bb_upper"] - df["bb_lower"]
    df["bb_position"] = (
        (close - df["bb_lower"]) / bb_range.replace(0, 1)
    ).clip(0, 1)

    # ── Volume Z-Score ────────────────────────────────────
    df["volume_zscore"] = calculate_volume_zscore(volume)

    # ── Returns ───────────────────────────────────────────
    returns = calculate_returns(close)
    for col_name, series in returns.items():
        df[col_name] = series

    # ── Candlestick features ──────────────────────────────
    #
    # high_low_ratio: range of the candle
    # close_open_ratio: where price closed vs opened
    # price_position: where close is within high-low range
    df["high_low_ratio"] = (
        (df["high"] - df["low"]) / close.replace(0, 1)
    )

    df["close_open_ratio"] = (
        (close - df["open"]) / df["open"].replace(0, 1)
    )

    hl_range = df["high"] - df["low"]
    df["price_position"] = (
        (close - df["low"]) / hl_range.replace(0, 1)
    ).clip(0, 1)

    # ── Moving averages ───────────────────────────────────
    df["sma_5"]  = close.rolling(5).mean().fillna(close)
    df["sma_20"] = close.rolling(20).mean().fillna(close)
    df["sma_50"] = close.rolling(50).mean().fillna(close)

    # ── Moving average crossover signals ─────────────────
    #
    # 1 = short MA above long MA (uptrend)
    # 0 = short MA below long MA (downtrend)
    df["ma_cross_5_20"] = (
        (df["sma_5"] > df["sma_20"]).astype(int)
    )

    # ── Drop rows with NaN ────────────────────────────────
    #
    # Rolling windows create NaN for early rows.
    # We drop them so models only see complete features.
    df = df.dropna().reset_index(drop=True)

    logger.info(
        "features_built",
        extra={
            "symbol": symbol,
            "rows": len(df),
            "features": len(df.columns)
        }
    )

    return df