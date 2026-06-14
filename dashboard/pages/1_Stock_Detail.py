import streamlit as st
import pandas as pd
from components.api_client import (
    get_all_stocks, get_price_history, get_price_summary,
    get_forecast, get_sentiment, get_news,
    trigger_forecast, get_health, get_latest_price,
    get_anomalies
)
from components.charts import (
    price_chart, forecast_chart, sentiment_chart
)
from components.metrics import (
    signal_badge, news_card, anomaly_card, health_indicator
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

    stocks  = get_all_stocks()
    symbols = [s["symbol"] for s in stocks] if stocks else ["AAPL"]

    symbol = st.selectbox("Select Stock", symbols, index=0)
    days   = st.selectbox(
        "Time period",
        [7, 14, 30, 60, 90],
        index=2,
        format_func=lambda x: f"{x} days"
    )

    st.divider()

    if st.button("🔄 Run Forecast", type="primary", use_container_width=True):
        with st.spinner("Training ML models (~30 seconds)..."):
            success = trigger_forecast(symbol)
            if success:
                st.success("Forecast running in background!")
                st.cache_data.clear()
            else:
                st.error("Failed to trigger forecast.")

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    health = get_health()
    health_indicator(health)

# ── Header ────────────────────────────────────────────────
stocks_list  = get_all_stocks()
company_name = next(
    (s["company_name"] for s in stocks_list if s["symbol"] == symbol),
    symbol
)

st.title(f"{symbol}")
st.caption(company_name)

# ── Current price header ──────────────────────────────────
latest = get_latest_price(symbol)
if latest:
    col_p, col_c, col_pct, col_h, col_l = st.columns(5)
    with col_p:
        st.metric("Current Price", f"${latest.get('close', 0):.2f}")
    with col_c:
        chg = latest.get("price_change")
        st.metric("Change", f"${chg:.2f}" if chg else "—")
    with col_pct:
        pct = latest.get("price_change_pct")
        st.metric("Change %", f"{pct:.2f}%" if pct else "—")
    with col_h:
        st.metric("Day High", f"${latest.get('high', 0):.2f}")
    with col_l:
        st.metric("Day Low", f"${latest.get('low', 0):.2f}")

st.divider()

# ── Tabs ──────────────────────────────────────────────────
#
# st.tabs() creates a tabbed interface.
# Each tab shows different data without page navigation.
tab_price, tab_forecast, tab_sentiment, tab_news, tab_anomalies = st.tabs([
    "📈 Price Chart",
    "🔮 Forecast",
    "💭 Sentiment",
    "📰 News",
    "🚨 Anomalies"
])

# ── Tab 1: Price Chart ────────────────────────────────────
with tab_price:
    st.subheader(f"{symbol} Price History — {days} days")

    prices = get_price_history(symbol, days=days)
    price_chart(prices, symbol, show_volume=True)

    # Daily summary table
    if prices:
        summary = get_price_summary(symbol, days=min(days, 30))
        if summary:
            with st.expander("View daily summary"):
                df = pd.DataFrame(summary)
                display = ["date", "open", "high", "low", "close", "volume"]
                available = [c for c in display if c in df.columns]
                for col in ["open", "high", "low", "close"]:
                    if col in df.columns:
                        df[col] = df[col].map("${:.2f}".format)
                st.dataframe(
                    df[available].sort_values("date", ascending=False),
                    hide_index=True,
                    use_container_width=True
                )

# ── Tab 2: Forecast ───────────────────────────────────────

with tab_forecast:
    st.subheader(f"{symbol} ML Forecast")

    # ── Trigger button with status ────────────────────────
    col_btn, col_status = st.columns([1, 3])

    with col_btn:
        run_clicked = st.button(
            "🔄 Run Forecast",
            type="primary",
            use_container_width=True,
            key="run_forecast_tab"
        )

    if run_clicked:
        with st.spinner(f"Training Prophet + XGBoost for {symbol}..."):
            success = trigger_forecast(symbol)
            if success:
                st.info(
                    "⏳ Models are training in background. "
                    "This takes ~30 seconds. "
                    "Click **Refresh Data** in sidebar when done."
                )
            else:
                st.error("❌ Could not trigger forecast. Check API logs.")

    # ── Fetch forecast ────────────────────────────────────
    forecast_data = get_forecast(symbol)

    if forecast_data:
        xgb     = forecast_data.get("xgb_signal")
        prophet = forecast_data.get("prophet_forecasts", [])

        # ── XGBoost signal ────────────────────────────────
        if xgb and xgb.get("direction_signal") is not None:
            st.subheader("Tomorrow's Direction Signal")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                signal_badge(
                    xgb.get("signal_label", ""),
                    xgb.get("confidence", 0)
                )
            with c2:
                st.metric("Confidence", f"{xgb.get('confidence', 0):.0%}")
            with c3:
                st.metric("Model Accuracy", f"{xgb.get('accuracy', 0):.0%}")
            with c4:
                st.metric("For Date", xgb.get("forecast_date", "—"))
        else:
            st.warning("XGBoost signal not yet generated.")

        st.divider()

        # ── Prophet forecast ──────────────────────────────
        if prophet:
            st.subheader("7-Day Price Forecast (Prophet)")
            prices_for_chart = get_price_history(symbol, days=30)
            forecast_chart(forecast_data, symbol, prices_for_chart)

            with st.expander("View forecast table"):
                import pandas as pd
                df = pd.DataFrame(prophet)
                if not df.empty:
                    df["predicted_price"] = df["predicted_price"].map(
                        lambda x: f"${x:.2f}" if x else "—"
                    )
                    df["lower_bound"] = df["lower_bound"].map(
                        lambda x: f"${x:.2f}" if x else "—"
                    )
                    df["upper_bound"] = df["upper_bound"].map(
                        lambda x: f"${x:.2f}" if x else "—"
                    )
                    st.dataframe(
                        df[["forecast_date", "predicted_price",
                            "lower_bound", "upper_bound"]].rename(columns={
                            "forecast_date":   "Date",
                            "predicted_price": "Predicted",
                            "lower_bound":     "Lower (80%)",
                            "upper_bound":     "Upper (80%)"
                        }),
                        hide_index=True,
                        use_container_width=True
                    )
        else:
            st.warning("Prophet forecast not yet generated.")

    else:
        # No forecast exists at all
        st.info(
            "📊 No forecast generated yet for this stock.\n\n"
            "Click **Run Forecast** above to generate:\n"
            "- Prophet 7-day price prediction with confidence bands\n"
            "- XGBoost UP/DOWN signal for tomorrow\n\n"
            "⏱️ This takes approximately 30-60 seconds."
        )

        # ── Show what data is available ───────────────────
        st.caption("Checking data availability...")

        from components.api_client import get
        price_data = get(f"/api/prices/{symbol}/history", {"days": 7})

        if price_data and price_data.get("total_records", 0) > 0:
            st.success(
                f"✅ {price_data['total_records']} price records "
                f"available for {symbol} — ready to forecast"
            )
        else:
            st.error(
                f"❌ No price data for {symbol} in ClickHouse.\n\n"
                "Run this on your Mac first:\n"
                "`python scripts/seed_prices.py`"
            )

# ── Tab 3: Sentiment ──────────────────────────────────────
with tab_sentiment:
    st.subheader(f"{symbol} Sentiment Analysis")

    sentiment_data = get_sentiment(symbol, days=14)

    if sentiment_data:
        overall = sentiment_data.get("overall_label", "neutral")
        score   = sentiment_data.get("overall_score", 0)
        period  = sentiment_data.get("period_days", 14)

        c1, c2, c3 = st.columns(3)
        with c1:
            if overall == "bullish":
                st.success(f"🟢 {overall.title()}")
            elif overall == "bearish":
                st.error(f"🔴 {overall.title()}")
            else:
                st.info(f"⚪ {overall.title()}")
        with c2:
            st.metric("Avg Score", f"{score:.3f}")
        with c3:
            st.metric("Period", f"{period} days")

        sentiment_chart(sentiment_data, symbol)

        points = sentiment_data.get("data", [])
        if points:
            with st.expander("View sentiment data"):
                df = pd.DataFrame(points)
                st.dataframe(df, hide_index=True,
                             use_container_width=True)
    else:
        st.info(
            "No sentiment data yet. "
            "Sentiment is collected from news articles and "
            "scored every 30 minutes by the Celery pipeline."
        )

# ── Tab 4: News ───────────────────────────────────────────
with tab_news:
    st.subheader(f"Latest News — {symbol}")

    col_limit, col_source = st.columns(2)
    with col_limit:
        limit = st.selectbox("Articles to show", [5, 10, 20], index=1)
    with col_source:
        source_filter = st.selectbox(
            "Filter by source",
            ["All", "newsapi", "rss_reuters",
             "rss_yahoo", "rss_marketwatch"],
            index=0
        )

    from components.api_client import get
    params = {"limit": limit}
    if source_filter != "All":
        params["source"] = source_filter

    data = get(f"/api/news/{symbol}", params)
    news = data.get("articles", []) if data else []

    if news:
        st.caption(f"Showing {len(news)} articles")
        for article in news:
            news_card(article)
    else:
        st.info(
            f"No news articles found for {symbol}. "
            "News is fetched every 30 minutes."
        )

# ── Tab 5: Anomalies ──────────────────────────────────────
with tab_anomalies:
    st.subheader(f"Anomalies — {symbol}")

    anomalies = get_anomalies(symbol)

    if not anomalies:
        st.success(f"✅ No anomalies detected for {symbol}")
    else:
        st.warning(f"⚠️ {len(anomalies)} anomalies detected")
        for a in anomalies:
            anomaly_card(a)