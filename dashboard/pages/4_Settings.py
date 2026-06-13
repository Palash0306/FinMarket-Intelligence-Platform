import streamlit as st
from components.api_client import (
    get_all_stocks, get_health,
    post, get
)
from components.metrics import health_indicator

st.set_page_config(
    page_title="Settings — FinMarket",
    page_icon="⚙️",
    layout="wide"
)

with st.sidebar:
    st.title("📈 FinMarket")
    st.divider()
    health = get_health()
    health_indicator(health)

st.title("⚙️ Settings")

# ── System status ─────────────────────────────────────────
st.subheader("System Status")
health = get_health()

if health:
    col1, col2, col3 = st.columns(3)
    with col1:
        db = health.get("database", "unknown")
        st.metric(
            "RDS Database",
            "Connected" if db == "connected" else "Error"
        )
    with col2:
        ch = health.get("clickhouse", "unknown")
        st.metric(
            "ClickHouse",
            "Connected" if ch == "connected" else "Error"
        )
    with col3:
        st.metric("API Version", "0.1.0")
else:
    st.error("Cannot reach API at localhost:8000")

st.divider()

# ── Tracked stocks ────────────────────────────────────────
st.subheader("Tracked Stocks")
stocks = get_all_stocks()

if stocks:
    import pandas as pd
    df = pd.DataFrame(stocks)
    display_cols = [
        "symbol", "company_name", "sector",
        "industry", "is_active"
    ]
    available = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[available],
        hide_index=True,
        use_container_width=True
    )
else:
    st.warning("Could not load stocks list.")

st.divider()

# ── API links ─────────────────────────────────────────────
st.subheader("Quick Links")

col1, col2, col3 = st.columns(3)
with col1:
    st.link_button(
        "📖 API Docs",
        "http://localhost:8000/docs",
        use_container_width=True
    )
with col2:
    st.link_button(
        "🌸 Flower (Celery)",
        "http://localhost:5555",
        use_container_width=True
    )
with col3:
    st.link_button(
        "🔬 MLflow",
        "http://localhost:5001",
        use_container_width=True
    )