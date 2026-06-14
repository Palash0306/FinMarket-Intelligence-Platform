import streamlit as st
import pandas as pd
import time
from components.api_client import (
    get_all_stocks,
    get_all_prices,
    get_all_signals,
    get_anomalies,
    get_health,
    get_price_history
)
from components.metrics import anomaly_card, health_indicator
from components.charts import mini_sparkline

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

    health = get_health()
    health_indicator(health)

    st.divider()

    # ── Auto-refresh toggle ───────────────────────────────
    #
    # st.session_state persists across reruns.
    # When auto_refresh is on, page reloads every 60 seconds.
    auto_refresh = st.toggle(
        "Auto-refresh (60s)",
        value=False,
        help="Automatically refresh data every 60 seconds"
    )

    if auto_refresh:
        st.caption("🔄 Refreshing every 60 seconds")

    st.divider()
    st.caption("**Stack**")
    st.caption("FastAPI + Streamlit")
    st.caption("Prophet + XGBoost")
    st.caption("LangGraph + Groq LLaMA3")
    st.caption("ClickHouse + pgvector")

# ── Auto refresh logic ────────────────────────────────────
if auto_refresh:
    time.sleep(60)
    st.cache_data.clear()
    st.rerun()

# ── Header ────────────────────────────────────────────────
col_title, col_refresh = st.columns([4, 1])
with col_title:
    st.title("📊 Market Overview")
    st.caption("Real-time data • Updated every 5 minutes by Celery")

with col_refresh:
    st.write("")
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Fetch data ────────────────────────────────────────────
with st.spinner("Loading market data..."):
    all_prices    = get_all_prices()
    all_signals   = get_all_signals()
    all_anomalies = get_anomalies()

# ── Summary metrics ───────────────────────────────────────
st.subheader("Market Summary")
col1, col2, col3, col4, col5 = st.columns(5)

up_signals     = sum(1 for s in all_signals if s.get("signal") == "UP")
down_signals   = sum(1 for s in all_signals if s.get("signal") == "DOWN")
high_anomalies = sum(1 for a in all_anomalies if a.get("severity") == "high")

with col1:
    st.metric("Stocks Tracked", len(all_prices))
with col2:
    st.metric(
        "Buy Signals ↑",
        up_signals,
        delta=f"of {len(all_signals)} signals"
    )
with col3:
    st.metric(
        "Sell Signals ↓",
        down_signals,
        delta=None
    )
with col4:
    st.metric(
        "High Alerts 🚨",
        high_anomalies,
        delta="action needed" if high_anomalies > 0 else None,
        delta_color="inverse"
    )
with col5:
    from datetime import datetime
    st.metric(
        "Last Updated",
        datetime.now().strftime("%H:%M:%S")
    )

st.divider()

# ── Watchlist table ───────────────────────────────────────
st.subheader("Watchlist")

signal_map = {s["symbol"]: s for s in all_signals}

if not all_prices:
    st.warning(
        "⚠️ No price data found. "
        "Make sure Docker is running: `docker compose up -d`"
    )
    st.code("python scripts/seed_prices.py", language="bash")
else:
    # ── Column headers ────────────────────────────────────
    h1, h2, h3, h4, h5 = st.columns([2, 1.5, 1.5, 1.5, 2])
    with h1: st.caption("**STOCK**")
    with h2: st.caption("**PRICE**")
    with h3: st.caption("**UPDATED**")
    with h4: st.caption("**ML SIGNAL**")
    with h5: st.caption("**7-DAY TREND**")

    st.divider()

    for price_data in all_prices:
        symbol       = price_data["symbol"]
        close        = price_data.get("close", 0)
        company_name = price_data.get("company_name", symbol)
        timestamp    = str(price_data.get("timestamp", ""))[:10]
        signal_data  = signal_map.get(symbol, {})
        signal       = signal_data.get("signal", "—")
        confidence   = signal_data.get("confidence", 0)

        col1, col2, col3, col4, col5 = st.columns([2, 1.5, 1.5, 1.5, 2])

        with col1:
            st.markdown(f"**{symbol}**")
            st.caption(company_name[:30])

        with col2:
            st.markdown(f"**${close:.2f}**")

        with col3:
            st.caption(timestamp)

        with col4:
            if signal == "UP":
                st.success(f"↑ {signal} {confidence:.0%}")
            elif signal == "DOWN":
                st.error(f"↓ {signal} {confidence:.0%}")
            else:
                st.caption("—")

        with col5:
            history = get_price_history(symbol, days=7)
            if history:
                fig = mini_sparkline(history, symbol)
                if fig:
                    st.plotly_chart(
                        fig,
                        use_container_width=True,
                        config={"displayModeBar": False},
                        key=f"spark_{symbol}"
                    )

        st.divider()

# ── Anomaly feed ──────────────────────────────────────────
st.subheader("🚨 Recent Alerts")

if not all_anomalies:
    st.success("✅ No anomalies detected — market looks normal")
else:
    # Show high severity first
    high = [a for a in all_anomalies if a.get("severity") == "high"]
    med  = [a for a in all_anomalies if a.get("severity") == "medium"]

    if high:
        st.error(f"🚨 {len(high)} HIGH severity anomaly detected")
        for a in high[:3]:
            anomaly_card(a)

    if med:
        with st.expander(f"⚠️ {len(med)} medium severity alerts"):
            for a in med[:5]:
                anomaly_card(a)