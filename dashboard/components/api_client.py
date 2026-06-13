# =========================================================
# API CLIENT
# =========================================================
#
# What is this in plain English?
#
# The dashboard never touches ClickHouse or RDS directly.
# It calls your FastAPI endpoints — the same ones you
# tested with curl during Phases 1-4.
#
# This file is the single place where all API calls live.
# Every dashboard page imports from here.
#
# Why centralise API calls here?
# If your API URL changes (e.g. deployed to EC2),
# you only change API_BASE_URL in one place.
# All pages update automatically.
#
# Connection chain:
# dashboard pages
#       ↓ import from
# THIS FILE
#       ↓ HTTP calls to
# FastAPI endpoints (localhost:8000)
#       ↓ which read from
# ClickHouse + RDS + pgvector

import requests
import streamlit as st
from typing import Optional

# ── API base URL ──────────────────────────────────────────
#
# localhost:8000 = FastAPI running in Docker
# In Phase 6 this becomes your EC2 public URL
API_BASE_URL = "http://api:8000"

# ── Request timeout ───────────────────────────────────────
TIMEOUT = 10


def get(endpoint: str, params: dict = None) -> Optional[dict]:
    """
    Makes a GET request to the FastAPI API.

    Uses st.cache_data to cache results for 60 seconds.
    This prevents hammering the API on every page refresh.

    Returns None on error so pages can handle gracefully.
    """
    try:
        response = requests.get(
            f"{API_BASE_URL}{endpoint}",
            params=params,
            timeout=TIMEOUT
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None


def post(endpoint: str, data: dict) -> Optional[dict]:
    """Makes a POST request to the FastAPI API."""
    try:
        response = requests.post(
            f"{API_BASE_URL}{endpoint}",
            json=data,
            timeout=60  # longer for AI chat
        )
        if response.status_code == 200:
            return response.json()
        # ── Show the actual error for debugging ───────────
        return None
    except requests.exceptions.Timeout:
        return {"error": "timeout"}
    except requests.exceptions.ConnectionError:
        return {"error": "connection"}
    except Exception as e:
        return {"error": str(e)}


# ── Cached data fetchers ──────────────────────────────────
#
# @st.cache_data(ttl=60) caches the result for 60 seconds.
# Streamlit re-runs the whole script on every interaction.
# Without caching, every button click would make new API calls.
# With caching, repeated calls within 60s use cached data.

@st.cache_data(ttl=60)
def get_all_stocks() -> list:
    """GET /api/stocks/ — all tracked stocks."""
    data = get("/api/stocks/")
    return data.get("stocks", []) if data else []


@st.cache_data(ttl=30)
def get_all_prices() -> list:
    """GET /api/prices/ — latest price for all stocks."""
    data = get("/api/prices/")
    return data.get("prices", []) if data else []


@st.cache_data(ttl=30)
def get_latest_price(symbol: str) -> Optional[dict]:
    """GET /api/prices/{symbol} — latest price for one stock."""
    return get(f"/api/prices/{symbol}")


@st.cache_data(ttl=60)
def get_price_history(symbol: str, days: int = 30) -> list:
    """GET /api/prices/{symbol}/history — historical prices."""
    data = get(f"/api/prices/{symbol}/history", {"days": days})
    return data.get("prices", []) if data else []


@st.cache_data(ttl=60)
def get_price_summary(symbol: str, days: int = 30) -> list:
    """GET /api/prices/{symbol}/summary — daily aggregates."""
    data = get(f"/api/prices/{symbol}/summary", {"days": days})
    return data if isinstance(data, list) else []


@st.cache_data(ttl=120)
def get_forecast(symbol: str) -> Optional[dict]:
    """GET /api/forecasts/{symbol} — ML forecast."""
    return get(f"/api/forecasts/{symbol}")


@st.cache_data(ttl=120)
def get_all_signals() -> list:
    """GET /api/forecasts/ — all stocks signals."""
    data = get("/api/forecasts/")
    return data.get("signals", []) if data else []


@st.cache_data(ttl=60)
def get_news(symbol: str, limit: int = 10) -> list:
    """GET /api/news/{symbol} — news articles."""
    data = get(f"/api/news/{symbol}", {"limit": limit})
    return data.get("articles", []) if data else []


@st.cache_data(ttl=60)
def get_sentiment(symbol: str, days: int = 7) -> Optional[dict]:
    """GET /api/news/{symbol}/sentiment — sentiment data."""
    return get(f"/api/news/{symbol}/sentiment", {"days": days})


@st.cache_data(ttl=60)
def get_anomalies(symbol: str = None) -> list:
    """GET /api/anomalies/ or /api/anomalies/{symbol}."""
    if symbol:
        data = get(f"/api/anomalies/{symbol}")
    else:
        data = get("/api/anomalies/")
    return data.get("anomalies", []) if data else []


def trigger_forecast(symbol: str) -> bool:
    """POST /api/forecasts/{symbol}/run — trigger ML models."""
    result = post(f"/api/forecasts/{symbol}/run", {})
    return result is not None


def ask_ai(question: str) -> Optional[dict]:
    """POST /api/chat/ — ask the AI agent."""
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/chat/",
            json={"question": question},
            timeout=60
        )
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.ConnectionError:
        return None
    except Exception:
        return None


def get_health() -> Optional[dict]:
    """GET /health — system health check."""
    return get("/health")