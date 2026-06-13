# =========================================================
# STOCK DETAIL PAGE
# =========================================================
#
# Full analysis for one selected stock:
# - Price chart (candlestick)
# - ML forecast chart (Prophet + XGBoost)
# - Sentiment trend chart
# - Latest news feed
# - Trigger forecast button
#
# Connection chain:
# api_client.py
#   → GET /api/prices/{symbol}/history
#   → GET /api/forecasts/{symbol}
#   → GET /api/news/{symbol}/sentiment
#   → GET /api/news/{symbol}
#   → POST /api/forecasts/{symbol}/run (on button click)

import streamlit as st
from components.api_client import (
    get_all_stocks,
    get_price_history,
    get_forecast,
    get_sentiment,
    get_news,
    trigger_forecast,
    get_health
)
from components.charts import (
    price_chart,
    forecast_chart,
    sentiment_chart
)
from components.metrics import (
    price_metric,
    signal_badge,
    news_card,
    health_indicator
)

st.set_page_config(
    page_title="Stock Detail — FinMarket",
    page_icon="📊",
    layout="wide"
)

# ── Sidebar ───────────────────────────────────────────────
with st.sidebar:
    st.title("📈 FinMarket")
    st.divider()

    # Stock selector
    stocks = get_all_stocks()
    symbols = [s["symbol"] for s in stocks] if stocks else ["AAPL"]

    symbol = st.selectbox(
        "Select Stock",
        symbols,
        index=0
    )

    st.divider()
    health = get_health()
    health_indicator(health)

# ── Header ────────────────────────────────────────────────
# Find company name
stocks_list = get_all_stocks()
company_name = next(
    (s["company_name"] for s in stocks_list if s["symbol"] == symbol),
    symbol
)

st.title(f"{symbol} — {company_name}")

# ── Controls ──────────────────────────────────────────────
col_days, col_btn, col_empty = st.columns([1, 1, 3])

with col_days:
    days = st.selectbox(
        "Time period",
        [7, 14, 30, 60, 90],
        index=2,
        format_func=lambda x: f"{x} days"
    )

with col_btn:
    st.write("")  # spacing
    if st.button("🔄 Run Forecast", type="primary"):
        with st.spinner("Training ML models..."):
            success = trigger_forecast(symbol)
            if success:
                st.success(
                    "Forecast triggered! "
                    "Check back in 30 seconds."
                )
                st.cache_data.clear()
            else:
                st.error("Could not trigger forecast.")

# ── Price Chart ───────────────────────────────────────────
st.subheader("Price History")
prices = get_price_history(symbol, days=days)
price_chart(prices, symbol, show_volume=True)

# ── Forecast Section ──────────────────────────────────────
st.subheader("ML Forecast")

forecast_data = get_forecast(symbol)

if forecast_data:
    xgb = forecast_data.get("xgb_signal")

    # Show XGBoost signal prominently
    if xgb:
        col_sig, col_conf, col_acc = st.columns(3)
        with col_sig:
            signal_badge(
                xgb.get("signal_label", ""),
                xgb.get("confidence", 0)
            )
        with col_conf:
            st.metric(
                "Confidence",
                f"{xgb.get('confidence', 0):.0%}"
            )
        with col_acc:
            st.metric(
                "Model Accuracy",
                f"{xgb.get('accuracy', 0):.0%}"
            )

    # Prophet forecast chart
    forecast_chart(forecast_data, symbol, prices)

    # Show forecast table
    prophet = forecast_data.get("prophet_forecasts", [])
    if prophet:
        with st.expander("View forecast table"):
            import pandas as pd
            df = pd.DataFrame(prophet)[
                ["forecast_date", "predicted_price",
                 "lower_bound", "upper_bound"]
            ]
            df.columns = ["Date", "Predicted", "Lower", "Upper"]
            df["Predicted"] = df["Predicted"].map("${:.2f}".format)
            df["Lower"]     = df["Lower"].map("${:.2f}".format)
            df["Upper"]     = df["Upper"].map("${:.2f}".format)
            st.dataframe(df, hide_index=True, use_container_width=True)
else:
    st.info(
        "No forecast yet. Click 'Run Forecast' to generate "
        "Prophet price predictions and XGBoost signal."
    )

# ── Sentiment ─────────────────────────────────────────────
st.subheader("Sentiment Trend")
sentiment_data = get_sentiment(symbol, days=14)

if sentiment_data:
    overall = sentiment_data.get("overall_label", "neutral")
    score   = sentiment_data.get("overall_score", 0)

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("Overall Sentiment", overall.title())
    with col_s2:
        st.metric("Sentiment Score", f"{score:.3f}")

    sentiment_chart(sentiment_data, symbol)
else:
    st.info("No sentiment data available.")

# ── Latest News ───────────────────────────────────────────
st.subheader("Latest News")
news = get_news(symbol, limit=10)

if news:
    for article in news:
        news_card(article)
else:
    st.info(f"No news articles found for {symbol}.")