# path: tests/test_news.py

# =========================================================
# NEWS API TESTS
# =========================================================
#
# Tests every endpoint in app/api/news.py.
# News data comes from RDS news_articles and
# stocktwits_posts tables.
#
# These tests will pass even with empty tables
# because we test the shape of the response,
# not the content (which depends on fetchers running).
#
# Connects to:
# tests/conftest.py → TestClient fixture
# app/api/news.py → endpoints being tested
# app/models/news.py → NewsArticle (RDS)
# app/models/stocktwits_post.py → StocktwitsPost (RDS)
# ─────────────────────────────────────────────────────────

import pytest
from fastapi.testclient import TestClient


class TestGetAllNews:
    """Tests for GET /api/news/"""

    def test_get_all_news_returns_200(
        self, client: TestClient
    ):
        """Endpoint is reachable."""
        response = client.get("/api/news/")
        assert response.status_code == 200

    def test_get_all_news_response_shape(
        self, client: TestClient
    ):
        """
        Response always has articles list and total count.
        Even when RDS news_articles table is empty.
        """
        response = client.get("/api/news/")
        data = response.json()
        assert "articles" in data
        assert "total" in data
        assert isinstance(data["articles"], list)
        assert isinstance(data["total"], int)

    def test_limit_parameter(
        self, client: TestClient
    ):
        """
        limit parameter must be 1-200.
        Tests Pydantic Query validation.
        """
        # Invalid: limit=0
        response = client.get("/api/news/?limit=0")
        assert response.status_code == 422

        # Invalid: limit=201
        response = client.get("/api/news/?limit=201")
        assert response.status_code == 422

        # Valid: limit=5
        response = client.get("/api/news/?limit=5")
        assert response.status_code == 200


class TestGetNewsForSymbol:
    """Tests for GET /api/news/{symbol}"""

    def test_invalid_symbol_returns_404(
        self, client: TestClient
    ):
        """
        Symbol not in stocks table → 404.
        Tests validate_symbol() helper.

        Connects to:
        validate_symbol() → Stock model → RDS stocks table
        """
        response = client.get("/api/news/FAKESYMBOL")
        assert response.status_code == 404

    def test_valid_symbol_returns_200(
        self, client: TestClient
    ):
        """
        AAPL is in stocks table from seed_stocks.py.
        Returns 200 even if no articles yet (empty list).
        """
        response = client.get("/api/news/AAPL")
        assert response.status_code == 200

    def test_valid_symbol_response_shape(
        self, client: TestClient
    ):
        """
        Response shape must always match NewsListResponse schema.
        symbol, total, articles must be present.
        """
        response = client.get("/api/news/AAPL")
        assert response.status_code == 200
        data = response.json()

        assert "symbol" in data
        assert "total" in data
        assert "articles" in data
        assert data["symbol"] == "AAPL"
        assert isinstance(data["articles"], list)

    def test_case_insensitive_symbol(
        self, client: TestClient
    ):
        """
        /api/news/aapl same as /api/news/AAPL.
        Both 200 because validate_symbol calls .upper()
        """
        upper = client.get("/api/news/AAPL")
        lower = client.get("/api/news/aapl")
        assert upper.status_code == lower.status_code == 200

    def test_source_filter(
        self, client: TestClient
    ):
        """
        source filter parameter works without error.
        Tests the optional ?source= query parameter.
        """
        response = client.get("/api/news/AAPL?source=newsapi")
        assert response.status_code == 200


class TestGetSentiment:
    """Tests for GET /api/news/{symbol}/sentiment"""

    def test_invalid_symbol_returns_404(
        self, client: TestClient
    ):
        response = client.get("/api/news/FAKESYMBOL/sentiment")
        assert response.status_code == 404

    def test_valid_symbol_returns_200(
        self, client: TestClient
    ):
        """
        Returns 200 even with no sentiment data yet.
        Empty data_points list is valid.
        """
        response = client.get("/api/news/AAPL/sentiment")
        assert response.status_code == 200

    def test_sentiment_response_shape(
        self, client: TestClient
    ):
        """
        Response must match SentimentResponse schema.
        symbol, period_days, overall_score, overall_label,
        data must all be present.
        """
        response = client.get("/api/news/AAPL/sentiment?days=7")
        assert response.status_code == 200
        data = response.json()

        assert "symbol" in data
        assert "period_days" in data
        assert "overall_score" in data
        assert "overall_label" in data
        assert "data" in data
        assert data["symbol"] == "AAPL"
        assert data["period_days"] == 7
        assert data["overall_label"] in [
            "bullish", "bearish", "neutral"
        ]

    def test_days_parameter_validation(
        self, client: TestClient
    ):
        """
        days must be 1-30.
        """
        # Invalid
        response = client.get(
            "/api/news/AAPL/sentiment?days=31"
        )
        assert response.status_code == 422

        # Valid
        response = client.get(
            "/api/news/AAPL/sentiment?days=7"
        )
        assert response.status_code == 200