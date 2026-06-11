# path: app/rag/rag_tools.py

# =========================================================
# RAG TOOLS — Data Retrieval Functions for LangGraph
# =========================================================
#
# What is this file in plain English?
#
# These are the "hands" of the AI agent.
# The LangGraph agent decides WHAT to look up,
# these tools actually DO the looking up.
#
# Think of the agent as a financial analyst:
# - The analyst decides "I need to check the price"
# - get_price_data() is the analyst opening Bloomberg
# - The analyst decides "I need recent news"
# - search_news() is the analyst reading Reuters
#
# Each tool:
# 1. Takes simple string inputs (from the LLM)
# 2. Queries the appropriate data source
# 3. Returns a formatted string the LLM can read
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# vector_store.py → search_similar_articles()
#       ↓ semantic news search
#
# ClickHouse ohlcv → get_price_data()
#       ↓ current + historical prices
#
# RDS forecasts table → get_forecast_data()
#       ↓ Prophet + XGBoost predictions
#
# RDS anomalies table → get_anomaly_data()
#       ↓ unusual price/volume events
#
# All tools used by agent.py LangGraph nodes
# ─────────────────────────────────────────────────────────

from app.rag.vector_store import search_similar_articles
from app.db.clickhouse import get_clickhouse_client
from app.db.session import SessionLocal
from app.models.forecast import Forecast
from app.models.anomaly import Anomaly
from app.utils.logger import get_logger

logger = get_logger(__name__)


def search_news(query: str, symbol: str = None) -> str:
    """
    Searches news articles using semantic similarity.

    Input:  "Apple earnings this quarter"
    Output: formatted string with top 5 relevant articles

    The LangGraph agent calls this when it detects
    the user is asking about news, events, or sentiment.

    Connection:
    vector_store.search_similar_articles()
        ↓ pgvector cosine similarity
        ↓ returns relevant articles
    THIS FUNCTION formats them as readable text
        ↓ LLM reads this as context
    """
    articles = search_similar_articles(
        query=query,
        symbol=symbol,
        limit=5
    )

    if not articles:
        return "No relevant news articles found."

    # ── Format articles as readable text ─────────────────
    #
    # The LLM reads this as context.
    # Clear formatting helps the LLM extract information.
    formatted = []
    for i, article in enumerate(articles, 1):
        sentiment = ""
        if article.get("sentiment_score") is not None:
            score = article["sentiment_score"]
            label = article.get("sentiment_label", "neutral")
            sentiment = f" [Sentiment: {label} ({score:.2f})]"

        formatted.append(
            f"{i}. [{article['source']}] {article['headline']}"
            f"{sentiment}\n"
            f"   {article['body'][:200]}..."
            f"\n   Published: {article.get('published_at', 'unknown')}"
            f"\n   Relevance: {article['similarity']:.0%}"
        )

    return "\n\n".join(formatted)


def get_price_data(symbol: str) -> str:
    """
    Gets current and recent price data for a symbol.

    Input:  "AAPL"
    Output: formatted string with price summary

    The agent calls this when user asks about
    current price, recent performance, or price trends.

    Connection:
    ClickHouse ohlcv table
        ↓ last 30 days of daily prices
        ↓ THIS FUNCTION calculates summary stats
    Returns formatted text for LLM context
    """
    try:
        client = get_clickhouse_client()

        # ── Get recent price summary ──────────────────────
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
              AND timestamp >= now() - toIntervalDay(30)
            GROUP BY date
            ORDER BY date DESC
            LIMIT 10
            """,
            {"symbol": symbol.upper()}
        )

        if not rows:
            return f"No price data found for {symbol}."

        latest     = rows[0]
        oldest     = rows[-1]
        latest_price = float(latest[1])
        old_price    = float(oldest[1])
        price_change = latest_price - old_price
        pct_change   = (price_change / old_price) * 100

        # ── Build summary ─────────────────────────────────
        summary = (
            f"Price data for {symbol.upper()}:\n"
            f"Current price: ${latest_price:.2f}\n"
            f"10-day change: {'+' if price_change > 0 else ''}"
            f"${price_change:.2f} ({pct_change:+.1f}%)\n"
            f"10-day high: ${max(r[2] for r in rows):.2f}\n"
            f"10-day low:  ${min(r[3] for r in rows):.2f}\n"
            f"Latest date: {latest[0]}\n\n"
            f"Recent prices (newest first):\n"
        )

        for row in rows[:5]:
            summary += f"  {row[0]}: ${float(row[1]):.2f}\n"

        return summary

    except Exception as e:
        logger.error(f"get_price_data_error: {e}")
        return f"Could not retrieve price data for {symbol}."


def get_forecast_data(symbol: str) -> str:
    """
    Gets ML model predictions for a symbol.

    Input:  "AAPL"
    Output: formatted string with Prophet forecast
            and XGBoost signal

    Agent calls this when user asks about future price,
    predictions, or buy/sell signals.

    Connection:
    RDS forecasts table (Prophet + XGBoost results)
        ↓ queried by THIS FUNCTION
    Returns formatted text for LLM context
    """
    db = SessionLocal()
    try:
        # ── Prophet 7-day forecast ────────────────────────
        prophet_rows = db.query(Forecast).filter(
            Forecast.symbol     == symbol.upper(),
            Forecast.model_type == "prophet"
        ).order_by(Forecast.forecast_date.asc()).limit(7).all()

        # ── XGBoost signal ────────────────────────────────
        xgb_row = db.query(Forecast).filter(
            Forecast.symbol     == symbol.upper(),
            Forecast.model_type == "xgboost"
        ).order_by(Forecast.forecast_date.desc()).first()

        if not prophet_rows and not xgb_row:
            return (
                f"No forecast available for {symbol}. "
                f"Trigger one at POST /api/forecasts/{symbol}/run"
            )

        result = f"ML Forecasts for {symbol.upper()}:\n\n"

        # ── Format XGBoost signal ─────────────────────────
        if xgb_row and xgb_row.direction_signal is not None:
            signal    = "UP ↑" if xgb_row.direction_signal == 1 else "DOWN ↓"
            conf      = xgb_row.confidence or 0
            accuracy  = xgb_row.mae or 0
            result   += (
                f"XGBoost Signal (tomorrow): {signal}\n"
                f"Confidence: {conf:.0%}\n"
                f"Model accuracy: {accuracy:.0%}\n\n"
            )

        # ── Format Prophet forecast ───────────────────────
        if prophet_rows:
            result += "7-day Prophet price forecast:\n"
            for row in prophet_rows:
                if row.predicted_price:
                    result += (
                        f"  {row.forecast_date}: "
                        f"${row.predicted_price:.2f} "
                        f"(range: ${row.lower_bound:.2f}"
                        f" - ${row.upper_bound:.2f})\n"
                    )

        return result

    except Exception as e:
        logger.error(f"get_forecast_data_error: {e}")
        return f"Could not retrieve forecast for {symbol}."
    finally:
        db.close()


def get_anomaly_data(symbol: str = None) -> str:
    """
    Gets recent anomalies — unusual price/volume events.

    Input:  "AAPL" or None (for all stocks)
    Output: formatted string describing anomalies

    Agent calls this when user asks about unusual moves,
    alerts, or market warnings.

    Connection:
    RDS anomalies table (written by detector.py Phase 3)
        ↓ queried by THIS FUNCTION
    Returns formatted text for LLM context
    """
    db = SessionLocal()
    try:
        query = db.query(Anomaly).order_by(
            Anomaly.detected_at.desc()
        )

        if symbol:
            query = query.filter(
                Anomaly.symbol == symbol.upper()
            )

        anomalies = query.limit(10).all()

        if not anomalies:
            target = f"for {symbol}" if symbol else "recently"
            return f"No anomalies detected {target}."

        result = "Recent anomalies detected:\n\n"
        for a in anomalies:
            result += (
                f"[{a.severity.upper()}] {a.symbol} — "
                f"{a.anomaly_type}\n"
                f"  {a.description}\n"
                f"  Z-score: {a.z_score:.2f} | "
                f"Detected: {a.detected_at[:10]}\n\n"
            )

        return result

    except Exception as e:
        logger.error(f"get_anomaly_data_error: {e}")
        return "Could not retrieve anomaly data."
    finally:
        db.close()


def get_sentiment_summary(symbol: str) -> str:
    """
    Gets aggregated sentiment for a symbol.

    Combines news article sentiment + stocktwits signals.

    Connection:
    RDS news_articles (sentiment_score filled by Phase 3)
    RDS stocktwits_posts (sentiment_score filled at ingestion)
        ↓ both queried here
    Returns sentiment summary text for LLM
    """
    from sqlalchemy import func
    from app.models.news import NewsArticle
    from app.models.stocktwits_post import StocktwitsPost

    db = SessionLocal()
    try:
        # ── News sentiment average ────────────────────────
        news_avg = db.query(
            func.avg(NewsArticle.sentiment_score)
        ).filter(
            NewsArticle.ticker_symbols.ilike(f"%{symbol}%"),
            NewsArticle.sentiment_score != None
        ).scalar()

        news_count = db.query(NewsArticle).filter(
            NewsArticle.ticker_symbols.ilike(f"%{symbol}%"),
            NewsArticle.sentiment_score != None
        ).count()

        # ── Stocktwits sentiment average ──────────────────
        st_avg = db.query(
            func.avg(StocktwitsPost.sentiment_score)
        ).filter(
            StocktwitsPost.ticker_symbol == symbol.upper(),
            StocktwitsPost.sentiment_score != None
        ).scalar()

        st_count = db.query(StocktwitsPost).filter(
            StocktwitsPost.ticker_symbol == symbol.upper()
        ).count()

        result = f"Sentiment summary for {symbol.upper()}:\n\n"

        if news_avg is not None:
            label = (
                "positive" if news_avg > 0.1
                else "negative" if news_avg < -0.1
                else "neutral"
            )
            result += (
                f"News sentiment: {label} "
                f"({float(news_avg):.3f}) "
                f"from {news_count} articles\n"
            )

        if st_avg is not None:
            label = (
                "bullish" if st_avg > 0.1
                else "bearish" if st_avg < -0.1
                else "neutral"
            )
            result += (
                f"Trader sentiment: {label} "
                f"({float(st_avg):.3f}) "
                f"from {st_count} signals\n"
            )

        return result if result != f"Sentiment summary for {symbol.upper()}:\n\n" \
               else f"No sentiment data for {symbol}."

    except Exception as e:
        logger.error(f"get_sentiment_error: {e}")
        return f"Could not retrieve sentiment for {symbol}."
    finally:
        db.close()