# path: tests/test_stocks.py

# =========================================================
# STOCKS API TESTS
# =========================================================
#
# We test every endpoint in app/api/stocks.py.
#
# pytest automatically finds test files that start with test_
# and functions that start with test_
#
# The client fixture comes from tests/conftest.py.
# We don't import it — pytest injects it automatically.

import pytest
from fastapi.testclient import TestClient


# =========================================================
# TEST — GET /api/stocks
# =========================================================
class TestGetStocks:
    """Tests for the list stocks endpoint."""

    def test_get_stocks_returns_200(self, client: TestClient):
        """
        Basic smoke test — endpoint is reachable and returns 200.

        A smoke test just checks the endpoint doesn't crash.
        It's the first test you always write.
        """
        response = client.get("/api/stocks/")

        # assert: if this is False, the test fails with the message
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"

    def test_get_stocks_returns_list(self, client: TestClient):
        """
        Verifies the response shape matches StockListResponse.

        We check:
        - response has 'stocks' key (list)
        - response has 'total' key (int)
        - stocks list is not empty (seed data exists)
        """
        response = client.get("/api/stocks/")
        data = response.json()

        assert "stocks" in data, "Response missing 'stocks' key"
        assert "total" in data, "Response missing 'total' key"
        assert isinstance(data["stocks"], list), "'stocks' should be a list"
        assert data["total"] > 0, "Should have stocks from seed data"

    def test_get_stocks_filter_by_sector(self, client: TestClient):
        """
        Verifies sector filter works correctly.

        All returned stocks should have 'Technology' in their sector.
        """
        response = client.get("/api/stocks/?sector=Technology")
        data = response.json()

        assert response.status_code == 200
        # Every returned stock must be in Technology sector
        for stock in data["stocks"]:
            assert "technology" in stock["sector"].lower(), \
                f"Stock {stock['symbol']} sector '{stock['sector']}' is not Technology"

    def test_get_stocks_total_matches_list_length(self, client: TestClient):
        """
        Verifies 'total' matches actual number of stocks returned.
        """
        response = client.get("/api/stocks/")
        data = response.json()

        assert data["total"] == len(data["stocks"]), \
            "total count should match actual list length"


# =========================================================
# TEST — GET /api/stocks/{symbol}
# =========================================================
class TestGetStock:
    """Tests for the single stock endpoint."""

    def test_get_existing_stock(self, client: TestClient):
        """
        AAPL was seeded — should return 200 with correct data.
        """
        response = client.get("/api/stocks/AAPL")

        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert data["company_name"] == "Apple Inc."

    def test_get_stock_case_insensitive(self, client: TestClient):
        """
        /api/stocks/aapl should work same as /api/stocks/AAPL.
        Our route calls symbol.upper() so this should always work.
        """
        response = client.get("/api/stocks/aapl")

        assert response.status_code == 200
        assert response.json()["symbol"] == "AAPL"

    def test_get_nonexistent_stock_returns_404(self, client: TestClient):
        """
        A symbol that doesn't exist should return 404.
        This tests our HTTPException handling.
        """
        response = client.get("/api/stocks/FAKESYMBOL")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# =========================================================
# TEST — POST /api/stocks
# =========================================================
class TestCreateStock:
    """Tests for the create stock endpoint."""

    def test_create_stock_success(self, client: TestClient):
        """
        Creates a new stock — should return 201 Created.
        """
        new_stock = {
            "symbol": "TEST",
            "company_name": "Test Company Inc.",
            "sector": "Technology",
            "industry": "Software"
        }

        response = client.post("/api/stocks/", json=new_stock)

        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "TEST"
        assert data["company_name"] == "Test Company Inc."
        # id and created_at should be set by DB
        assert "id" in data
        assert "created_at" in data

    def test_create_duplicate_stock_returns_409(self, client: TestClient):
        """
        Creating AAPL again should return 409 Conflict.
        Tests our duplicate check logic.
        """
        duplicate = {
            "symbol": "AAPL",
            "company_name": "Apple Inc."
        }

        response = client.post("/api/stocks/", json=duplicate)

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    def test_create_stock_lowercase_symbol_auto_uppercased(
        self, client: TestClient
    ):
        """
        Sending lowercase symbol should be auto-uppercased.
        Tests our @field_validator in StockCreate.
        """
        stock = {
            "symbol": "tsla",       # lowercase
            "company_name": "Tesla Inc."
        }

        response = client.post("/api/stocks/", json=stock)

        assert response.status_code == 201
        # Symbol should be uppercased in the response
        assert response.json()["symbol"] == "TSLA"

    def test_create_stock_missing_required_field(self, client: TestClient):
        """
        Omitting company_name should return 422 Unprocessable Entity.
        Tests pydantic validation — FastAPI returns 422 automatically.
        """
        incomplete = {
            "symbol": "INCOMPLETE"
            # company_name is missing
        }

        response = client.post("/api/stocks/", json=incomplete)

        # 422 = pydantic validation failed
        assert response.status_code == 422


# =========================================================
# TEST — PATCH /api/stocks/{symbol}
# =========================================================
class TestUpdateStock:
    """Tests for the update stock endpoint."""

    def test_update_stock_sector(self, client: TestClient):
        """
        Updates just the sector — other fields unchanged.
        Tests exclude_unset=True logic in PATCH handler.
        """
        update = {"sector": "Big Tech"}

        response = client.patch("/api/stocks/MSFT", json=update)

        assert response.status_code == 200
        assert response.json()["sector"] == "Big Tech"
        # company_name should be unchanged
        assert response.json()["company_name"] == "Microsoft Corporation"

    def test_update_nonexistent_stock(self, client: TestClient):
        """
        Updating a stock that doesn't exist should return 404.
        """
        response = client.patch(
            "/api/stocks/DOESNOTEXIST",
            json={"sector": "Technology"}
        )
        assert response.status_code == 404


# =========================================================
# TEST — DELETE /api/stocks/{symbol}
# =========================================================
class TestDeleteStock:
    """Tests for the soft delete endpoint."""

    def test_soft_delete_stock(self, client: TestClient):
        """
        Deleting a stock sets is_active=False.
        Stock should no longer appear in the default list.
        """
        # First verify TEST stock exists and is active
        get_response = client.get("/api/stocks/TEST")
        assert get_response.status_code == 200

        # Soft delete it
        delete_response = client.delete("/api/stocks/TEST")
        assert delete_response.status_code == 200
        assert "deactivated" in delete_response.json()["message"].lower()

        # Now it should not appear in the active list
        list_response = client.get("/api/stocks/")
        symbols = [s["symbol"] for s in list_response.json()["stocks"]]
        assert "TEST" not in symbols, \
            "Deactivated stock should not appear in active list"