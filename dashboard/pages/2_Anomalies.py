
import streamlit as st
import pandas as pd
from components.api_client import get_anomalies, get_all_stocks, get_health
from components.metrics import anomaly_card, health_indicator

st.set_page_config(
    page_title="Anomalies — FinMarket",
    page_icon="🚨",
    layout="wide"
)

with st.sidebar:
    st.title("📈 FinMarket")
    st.divider()
    health = get_health()
    health_indicator(health)

st.title("Anomaly Detection")
st.caption(
    "Unusual price and volume events detected by "
    "statistical z-score analysis"
)

# ── Filters ───────────────────────────────────────────────
col_sym, col_sev = st.columns(2)

with col_sym:
    stocks  = get_all_stocks()
    symbols = ["All"] + [s["symbol"] for s in stocks]
    selected_symbol = st.selectbox("Filter by stock", symbols)

with col_sev:
    severity_filter = st.selectbox(
        "Filter by severity",
        ["All", "high", "medium"]
    )

# ── Fetch anomalies ───────────────────────────────────────
if selected_symbol == "All":
    anomalies = get_anomalies()
else:
    anomalies = get_anomalies(selected_symbol)

# Apply severity filter
if severity_filter != "All":
    anomalies = [
        a for a in anomalies
        if a.get("severity") == severity_filter
    ]

# ── Summary metrics ───────────────────────────────────────
col1, col2, col3 = st.columns(3)
high   = sum(1 for a in anomalies if a.get("severity") == "high")
medium = sum(1 for a in anomalies if a.get("severity") == "medium")

with col1:
    st.metric("Total Anomalies", len(anomalies))
with col2:
    st.metric("High Severity", high)
with col3:
    st.metric("Medium Severity", medium)

st.divider()

# ── Anomaly list ──────────────────────────────────────────
if not anomalies:
    st.success("✅ No anomalies detected matching your filters.")
else:
    # Show as cards
    for anomaly in anomalies:
        anomaly_card(anomaly)

    # Also show as table for easy scanning
    with st.expander("View as table"):
        df = pd.DataFrame(anomalies)
        if not df.empty:
            display_cols = [
                "symbol", "anomaly_type", "severity",
                "z_score", "description", "detected_at"
            ]
            available = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[available],
                hide_index=True,
                use_container_width=True
            )