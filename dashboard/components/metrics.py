# =========================================================
# REUSABLE METRIC COMPONENTS
# =========================================================
#
# Small reusable UI components used across multiple pages.
# Keeps page files clean — logic lives here, not there.

import streamlit as st
from typing import Optional


def price_metric(
    symbol: str,
    price: float,
    change: Optional[float] = None,
    change_pct: Optional[float] = None
) -> None:
    """
    Renders a price metric card.

    Shows:
    - Symbol name
    - Current price
    - Change amount and percentage (green if up, red if down)
    """
    if change_pct is not None:
        delta_str = f"{change_pct:+.2f}%"
    elif change is not None:
        delta_str = f"{change:+.2f}"
    else:
        delta_str = None

    st.metric(
        label=symbol,
        value=f"${price:.2f}",
        delta=delta_str
    )


def signal_badge(signal: str, confidence: float) -> None:
    """
    Renders a colored signal badge (UP/DOWN).

    Green for UP, Red for DOWN.
    Shows confidence percentage.
    """
    if signal == "UP":
        st.success(f"↑ {signal} — {confidence:.0%} confidence")
    elif signal == "DOWN":
        st.error(f"↓ {signal} — {confidence:.0%} confidence")
    else:
        st.info("No signal available")


def anomaly_card(anomaly: dict) -> None:
    """
    Renders one anomaly as a colored alert card.

    HIGH severity → red
    MEDIUM severity → yellow
    """
    severity = anomaly.get("severity", "medium")
    symbol   = anomaly.get("symbol", "")
    atype    = anomaly.get("anomaly_type", "").replace("_", " ").title()
    desc     = anomaly.get("description", "")
    z_score  = anomaly.get("z_score", 0)
    detected = anomaly.get("detected_at", "")[:10]

    if severity == "high":
        st.error(
            f"🚨 **{symbol}** — {atype} "
            f"(z={z_score:.1f}) — {detected}\n\n{desc}"
        )
    else:
        st.warning(
            f"⚠️ **{symbol}** — {atype} "
            f"(z={z_score:.1f}) — {detected}\n\n{desc}"
        )


def news_card(article: dict) -> None:
    """
    Renders one news article as a card.

    Shows headline, source, sentiment, and link.
    """
    headline  = article.get("headline", "No headline")
    source    = article.get("source", "unknown")
    sentiment = article.get("sentiment_label", "neutral")
    score     = article.get("sentiment_score")
    url       = article.get("url", "#")
    published = article.get("published_at", "")[:10]

    # Sentiment color
    if sentiment == "positive":
        sentiment_color = "🟢"
    elif sentiment == "negative":
        sentiment_color = "🔴"
    else:
        sentiment_color = "⚪"

    score_str = f" ({score:.2f})" if score is not None else ""

    with st.container():
        st.markdown(f"**[{headline}]({url})**")
        st.caption(
            f"{sentiment_color} {sentiment}{score_str} "
            f"| {source} | {published}"
        )
        st.divider()


def health_indicator(health: dict) -> None:
    """
    Shows system health status in the sidebar.
    """
    if not health:
        st.sidebar.error("⚠️ API unreachable")
        return

    db = health.get("database", "unknown")
    ch = health.get("clickhouse", "unknown")

    db_icon = "🟢" if db == "connected" else "🔴"
    ch_icon = "🟢" if ch == "connected" else "🔴"

    st.sidebar.markdown(
        f"{db_icon} RDS: {db}  \n"
        f"{ch_icon} ClickHouse: {ch}"
    )