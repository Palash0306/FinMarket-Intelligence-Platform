# =========================================================
# REUSABLE CHART COMPONENTS
# =========================================================
#
# What is this in plain English?
#
# Every page that shows price charts uses the same
# chart code. Instead of copy-pasting chart code into
# every page, we define chart functions here once
# and import them everywhere.
#
# Uses Plotly for interactive charts — users can:
# - Hover to see exact values
# - Zoom in/out
# - Pan across time
# - Click legend items to show/hide series
#
# Connection chain:
# api_client.py → fetches price/forecast data
# THESE FUNCTIONS → render Plotly charts
# Dashboard pages → import and call these functions

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import streamlit as st
from typing import Optional


def price_chart(
    prices: list,
    symbol: str,
    show_volume: bool = True
) -> None:
    """
    Renders an interactive candlestick price chart.

    A candlestick chart shows:
    - Green candle = price closed ABOVE where it opened (up day)
    - Red candle   = price closed BELOW where it opened (down day)
    - Wick lines   = the high and low of that day

    Args:
        prices: list of price dicts from api_client
        symbol: ticker symbol for title
        show_volume: whether to show volume bar chart below
    """
    if not prices:
        st.info(f"No price data available for {symbol}")
        return

    df = pd.DataFrame(prices)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # ── Create figure with subplots ───────────────────────
    #
    # rows=2 if showing volume, rows=1 otherwise
    # row_heights controls how tall each subplot is
    if show_volume and "volume" in df.columns:
        from plotly.subplots import make_subplots
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.75, 0.25]
        )

        # ── Candlestick chart (top) ───────────────────────
        fig.add_trace(
            go.Candlestick(
                x=df["timestamp"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name=symbol,
                increasing_line_color="#1D9E75",
                decreasing_line_color="#E24B4A"
            ),
            row=1, col=1
        )

        # ── Volume bars (bottom) ──────────────────────────
        colors = [
            "#1D9E75" if c >= o else "#E24B4A"
            for c, o in zip(df["close"], df["open"])
        ]
        fig.add_trace(
            go.Bar(
                x=df["timestamp"],
                y=df["volume"],
                name="Volume",
                marker_color=colors,
                opacity=0.7
            ),
            row=2, col=1
        )

        fig.update_yaxes(title_text="Price ($)", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)

    else:
        fig = go.Figure()
        fig.add_trace(
            go.Candlestick(
                x=df["timestamp"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name=symbol,
                increasing_line_color="#1D9E75",
                decreasing_line_color="#E24B4A"
            )
        )

    # ── Layout ────────────────────────────────────────────
    fig.update_layout(
        title=f"{symbol} Price Chart",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=500,
        showlegend=False,
        margin=dict(l=0, r=0, t=40, b=0)
    )

    st.plotly_chart(fig, use_container_width=True)


def forecast_chart(
    forecast_data: dict,
    symbol: str,
    price_history: list = None
) -> None:
    """
    Renders Prophet 7-day forecast with confidence bands.

    Shows:
    - Historical prices (last 30 days) as blue line
    - Forecast line (predicted prices) as green line
    - Confidence band (upper/lower bounds) as shaded area
    - XGBoost signal as an annotation

    The shaded band = 80% confidence interval.
    Price will likely be within this range 80% of the time.
    """
    if not forecast_data:
        st.info("No forecast available. Click 'Run Forecast' to generate.")
        return

    prophet = forecast_data.get("prophet_forecasts", [])
    xgb     = forecast_data.get("xgb_signal")

    if not prophet:
        st.info("No Prophet forecast data.")
        return

    fig = go.Figure()

    # ── Historical prices ─────────────────────────────────
    if price_history:
        hist_df = pd.DataFrame(price_history)
        hist_df["timestamp"] = pd.to_datetime(hist_df["timestamp"])
        daily = hist_df.groupby(
            hist_df["timestamp"].dt.date
        )["close"].last().reset_index()

        fig.add_trace(go.Scatter(
            x=daily["timestamp"],
            y=daily["close"],
            mode="lines",
            name="Historical",
            line=dict(color="#378ADD", width=2)
        ))

    # ── Forecast dates and values ─────────────────────────
    forecast_df = pd.DataFrame(prophet)

    # ── Confidence band (shaded area) ────────────────────
    #
    # Plotly fills between upper and lower bound.
    # fill="tonexty" fills to the previous trace.
    # We add upper first, then lower with fill.
    fig.add_trace(go.Scatter(
        x=forecast_df["forecast_date"],
        y=forecast_df["upper_bound"],
        mode="lines",
        line=dict(width=0),
        name="Upper bound",
        showlegend=False
    ))

    fig.add_trace(go.Scatter(
        x=forecast_df["forecast_date"],
        y=forecast_df["lower_bound"],
        mode="lines",
        line=dict(width=0),
        fill="tonexty",
        fillcolor="rgba(29, 158, 117, 0.15)",
        name="80% confidence",
    ))

    # ── Forecast line ─────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=forecast_df["forecast_date"],
        y=forecast_df["predicted_price"],
        mode="lines+markers",
        name="Forecast",
        line=dict(color="#1D9E75", width=2, dash="dash"),
        marker=dict(size=6)
    ))

    # ── XGBoost signal annotation ─────────────────────────
    if xgb:
        signal_color = "#1D9E75" if xgb["signal_label"] == "UP" else "#E24B4A"
        signal_arrow = "↑" if xgb["signal_label"] == "UP" else "↓"
        fig.add_annotation(
            x=0.02, y=0.95,
            xref="paper", yref="paper",
            text=(
                f"XGBoost: {signal_arrow} {xgb['signal_label']} "
                f"({xgb['confidence']:.0%} confidence)"
            ),
            showarrow=False,
            bgcolor=signal_color,
            font=dict(color="white", size=12),
            borderpad=6
        )

    fig.update_layout(
        title=f"{symbol} — 7-Day Price Forecast",
        xaxis_title="Date",
        yaxis_title="Price ($)",
        template="plotly_dark",
        height=450,
        margin=dict(l=0, r=0, t=40, b=0)
    )

    st.plotly_chart(fig, use_container_width=True)


def sentiment_chart(sentiment_data: dict, symbol: str) -> None:
    """
    Renders a sentiment time series bar chart.

    Each bar = one day's average sentiment.
    Green = bullish, Red = bearish, Gray = neutral.
    """
    if not sentiment_data:
        st.info("No sentiment data available.")
        return

    data_points = sentiment_data.get("data", [])
    if not data_points:
        st.info("No sentiment data points.")
        return

    df = pd.DataFrame(data_points)

    # Color each bar based on sentiment label
    colors = []
    for label in df["label"]:
        if label == "bullish":
            colors.append("#1D9E75")
        elif label == "bearish":
            colors.append("#E24B4A")
        else:
            colors.append("#888780")

    fig = go.Figure(go.Bar(
        x=df["date"],
        y=df["avg_score"],
        marker_color=colors,
        name="Sentiment",
        hovertemplate=(
            "Date: %{x}<br>"
            "Score: %{y:.3f}<br>"
            "<extra></extra>"
        )
    ))

    # Add zero line
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="white",
        opacity=0.3
    )

    fig.update_layout(
        title=f"{symbol} Daily Sentiment Score",
        xaxis_title="Date",
        yaxis_title="Sentiment (-1.0 to +1.0)",
        template="plotly_dark",
        height=300,
        margin=dict(l=0, r=0, t=40, b=0)
    )

    st.plotly_chart(fig, use_container_width=True)


def mini_sparkline(prices: list, symbol: str) -> go.Figure:
    """
    Creates a tiny sparkline chart for the watchlist.

    A sparkline is a mini chart — no axes, no labels.
    Just the shape of the price movement.
    Green if up, red if down.
    """
    if not prices or len(prices) < 2:
        return None

    closes = [p["close"] for p in prices[-10:]]  # last 10 points
    color  = "#1D9E75" if closes[-1] >= closes[0] else "#E24B4A"

    fig = go.Figure(go.Scatter(
        y=closes,
        mode="lines",
        line=dict(color=color, width=1.5),
        showlegend=False
    ))

    fig.update_layout(
        height=50,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False)
    )

    return fig