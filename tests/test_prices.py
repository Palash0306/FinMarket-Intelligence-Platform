# path: tests/test_prices.py

# =========================================================
# PRICES API TESTS
# =========================================================
#
# What does this file test in plain English?
#
# Tests every endpoint in app/api/prices.py.
# Because prices come from ClickHouse (not RDS),
# some tests will return 404 or 503 in a dev environment
# where ClickHouse might not have data yet.
# We test both success paths AND empty-data paths.
#
# Connects to:
# tests/conftest.py → TestClient(app) client fixture
# app/main.py → app (via TestClient)
# app/api/prices.py → the endpoints being tested
# app/db/clickhouse.py → real ClickHouse (or empty)
# ─────────────────────────────────────────────────────────

import pytest
from fastapi.testclient import TestClient


class TestGetAllPrices:
    """Tests for GET /api/prices/ — all stocks watchlist"""

    def test_get_all_prices_returns_200(
        self, client: TestClient
    ):
        """
        Endpoint is reachable.
        Returns 200 when ClickHouse is running in Docker.
        Returns 503 when running tests locally (outside Docker)
        because 'clickhouse' hostname doesn't resolve on Mac.
        Both are valid — we just check the endpoint exists.
        """
        response = client.get("/api/prices/")

        # 200 = ClickHouse running (inside Docker)
        # 503 = ClickHouse unreachable (running tests on Mac)
        # Both mean the endpoint EXISTS and handled the request
        assert response.status_code in [200, 503], \
            f"Expected 200 or 503, got {response.status_code}"

    def test_get_all_prices_has_correct_shape(
        self, client: TestClient
    ):
        """
        If ClickHouse is reachable, response shape is correct.
        If not reachable, we skip the shape check.
        """
        response = client.get("/api/prices/")

        # Only check shape if ClickHouse was reachable
        if response.status_code == 200:
            data = response.json()
            assert "prices" in data
            assert "total" in data
            assert isinstance(data["prices"], list)
            assert isinstance(data["total"], int)

        # 503 is acceptable when ClickHouse not available
        elif response.status_code == 503:
            # Endpoint exists, ClickHouse just not available locally
            # This is expected when running tests outside Docker
            pass

        else:
            # Any other status code is a real failure
            assert False, \
                f"Unexpected status code: {response.status_code}"

class TestGetLatestPrice:
    """Tests for GET /api/prices/{symbol}"""

    def test_invalid_symbol_returns_404(
        self, client: TestClient
    ):
        """
        A symbol not in our stocks table returns 404.
        Tests validate_symbol() helper in prices.py.

        Connects to:
        validate_symbol() → Stock model → RDS stocks table
        """
        response = client.get("/api/prices/FAKESYMBOL")
        assert response.status_code == 404

    def test_valid_symbol_no_data_returns_404(
        self, client: TestClient
    ):
        """
        A valid symbol with no ClickHouse data yet.
        Returns 404 with a descriptive message.

        AAPL is in our RDS stocks table (from seed_stocks.py)
        but ClickHouse might be empty in test environment.
        """
        response = client.get("/api/prices/AAPL")
        # Either 200 (data exists) or 404 (no data yet)
        # Both are valid in test environment
        assert response.status_code in [200, 404, 503]

    def test_case_insensitive_symbol(
        self, client: TestClient
    ):
        """
        /api/prices/aapl should work same as /api/prices/AAPL.
        validate_symbol() calls symbol.upper().
        """
        response_upper = client.get("/api/prices/AAPL")
        response_lower = client.get("/api/prices/aapl")
        # Both should return the same status code
        assert response_upper.status_code == response_lower.status_code


class TestGetPriceHistory:
    """Tests for GET /api/prices/{symbol}/history"""

    def test_invalid_symbol_returns_404(
        self, client: TestClient
    ):
        response = client.get("/api/prices/FAKESYMBOL/history")
        assert response.status_code == 404

    def test_days_parameter_validation(
        self, client: TestClient
    ):
        """
        days must be between 1 and 90.
        Values outside that range return 422.
        Pydantic Query(ge=1, le=90) handles this.
        """
        # days=0 → invalid (ge=1 fails)
        response = client.get("/api/prices/AAPL/history?days=0")
        assert response.status_code == 422

        # days=91 → invalid (le=90 fails)
        response = client.get("/api/prices/AAPL/history?days=91")
        assert response.status_code == 422

        # days=7 → valid
        response = client.get("/api/prices/AAPL/history?days=7")
        assert response.status_code in [200, 404, 503]

    def test_history_response_shape(
        self, client: TestClient
    ):
        """
        If data exists, response must have correct fields.
        """
        response = client.get("/api/prices/AAPL/history?days=7")
        if response.status_code == 200:
            data = response.json()
            assert "symbol" in data
            assert "period_days" in data
            assert "total_records" in data
            assert "prices" in data
            assert data["period_days"] == 7