# =========================================================
# HOME PAGE — Market Overview
# =========================================================
#
# What this page shows:
# - System health status
# - All 10 stocks watchlist with prices + sparklines
# - ML signals (UP/DOWN) for each stock
# - Recent anomaly alerts
# - Quick stats
#
# This is the first page users see.
# It gives a complete market snapshot at a glance.
#
# Connection chain:
# api_client.py
#   → GET /api/prices/         (all latest prices)
#   → GET /api/forecasts/      (all signals)
#   → GET /api/anomalies/      (recent alerts)
#   → GET /health              (system status)
# components/metrics.py → renders cards
# components/charts.py  → renders sparklines

import streamlit as st
import pandas as pd
from components.api_client import (
    get_all_stocks,
    get_all_prices,
    get_all_signals,
    get_anomalies,
    get_health,
    get_price_history
)
from components.metrics import (
    anomaly_card,
    health_indicator
)
from components.charts import mini_sparkline

# ── Page config ───────────────────────────────────────────
st.set_page_config(
    page_title="FinMarket Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Sidebar ───────────────────────────────────────────────
with st.sidebar:
    st.title("📈 FinMarket")
    st.caption("Financial Intelligence Platform")
    st.divider()

    # Health check
    health = get_health()
    health_indicator(health)

    st.divider()
    st.caption("Built with FastAPI + Streamlit")
    st.caption("ML: Prophet + XGBoost")
    st.caption("AI: LangGraph + Groq LLaMA3")

# ── Header ────────────────────────────────────────────────
st.title("Market Overview")
st.caption("Real-time data updated every 5 minutes")

# ── Top metrics row ───────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)

all_prices  = get_all_prices()
all_signals = get_all_signals()
all_anomalies = get_anomalies()

# Count gainers and losers
gainers = sum(
    1 for p in all_prices
    if p.get("close", 0) > 0
)

high_anomalies = sum(
    1 for a in all_anomalies
    if a.get("severity") == "high"
)

up_signals = sum(
    1 for s in all_signals
    if s.get("signal") == "UP"
)

with col1:
    st.metric("Tracked Stocks", len(all_prices))
with col2:
    st.metric("Buy Signals", f"{up_signals}/{len(all_signals)}")
with col3:
    st.metric("Active Alerts", high_anomalies,
              delta="high severity" if high_anomalies > 0 else None,
              delta_color="inverse")
with col4:
    st.metric("Data Sources", "4",
              help="yfinance, NewsAPI, RSS, Alpha Vantage")

st.divider()

# ── Watchlist ─────────────────────────────────────────────
st.subheader("Watchlist")

# Build signal lookup dict
signal_map = {s["symbol"]: s for s in all_signals}

if not all_prices:
    st.warning(
        "No price data available. "
        "Make sure Docker is running and prices are seeded."
    )
else:
    # ── Display each stock in a row ───────────────────────
    for price_data in all_prices:
        symbol       = price_data["symbol"]
        close        = price_data.get("close", 0)
        company_name = price_data.get("company_name", symbol)
        timestamp    = str(price_data.get("timestamp", ""))[:10]

        # Get ML signal for this symbol
        signal_data = signal_map.get(symbol, {})
        signal      = signal_data.get("signal", "—")
        confidence  = signal_data.get("confidence", 0)

        # Create row with columns
        col_name, col_price, col_change, col_signal, col_chart = \
            st.columns([2, 1.5, 1.5, 1.5, 2])

        with col_name:
            st.markdown(f"**{symbol}**")
            st.caption(company_name)

        with col_price:
            st.metric(
                label="Price",
                value=f"${close:.2f}",
                label_visibility="collapsed"
            )

        with col_change:
            st.caption(f"Updated: {timestamp}")

        with col_signal:
            if signal == "UP":
                st.success(f"↑ {signal} {confidence:.0%}")
            elif signal == "DOWN":
                st.error(f"↓ {signal} {confidence:.0%}")
            else:
                st.caption("No signal")

        with col_chart:
            # Mini sparkline from recent prices
            history = get_price_history(symbol, days=7)
            if history:
                fig = mini_sparkline(history, symbol)
                if fig:
                    st.plotly_chart(
                        fig,
                        use_container_width=True,
                        config={"displayModeBar": False}
                    )

        st.divider()

# ── Recent Anomalies ──────────────────────────────────────
st.subheader("Recent Alerts")

if not all_anomalies:
    st.success("✅ No anomalies detected recently")
else:
    for anomaly in all_anomalies[:5]:
        anomaly_card(anomaly)

    if len(all_anomalies) > 5:
        st.caption(
            f"+ {len(all_anomalies) - 5} more alerts. "
            f"See the Anomalies page for full list."
        )