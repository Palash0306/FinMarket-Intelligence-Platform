# path: tests/test_stocks.py

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models.stock import Stock


# =========================================================
# CLEANUP FIXTURE
# =========================================================
#
# This runs BEFORE the test session starts.
# Deletes any leftover test stocks from previous runs
# so tests always start with a clean slate.
#
# scope="session" means it runs once per pytest session
# autouse=True means it runs automatically — no need to
# explicitly request it in each test class
@pytest.fixture(scope="session", autouse=True)
def cleanup_test_stocks():
    """
    Removes test symbols from RDS before tests run.
    Prevents 409 conflicts from previous test runs.
    """
    db = SessionLocal()
    try:
        # Delete any leftover test stocks
        # These are symbols only created by tests — never real stocks
        test_symbols = ["TEST", "TSLA", "INCOMPLETE"]
        for symbol in test_symbols:
            stock = db.query(Stock).filter(
                Stock.symbol == symbol
            ).first()
            if stock:
                db.delete(stock)
        db.commit()
    finally:
        db.close()

    yield  # tests run here

    # Cleanup AFTER tests too — leave DB tidy
    db = SessionLocal()
    try:
        for symbol in test_symbols:
            stock = db.query(Stock).filter(
                Stock.symbol == symbol
            ).first()
            if stock:
                db.delete(stock)
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# =========================================================
# TEST — GET /api/stocks
# =========================================================
class TestGetStocks:

    def test_get_stocks_returns_200(self, client: TestClient):
        response = client.get("/api/stocks/")
        assert response.status_code == 200

    def test_get_stocks_returns_list(self, client: TestClient):
        response = client.get("/api/stocks/")
        data = response.json()
        assert "stocks" in data
        assert "total" in data
        assert isinstance(data["stocks"], list)
        assert data["total"] > 0

    def test_get_stocks_filter_by_sector(self, client: TestClient):
        response = client.get("/api/stocks/?sector=Technology")
        data = response.json()
        assert response.status_code == 200
        for stock in data["stocks"]:
            assert "technology" in stock["sector"].lower()

    def test_get_stocks_total_matches_list_length(self, client: TestClient):
        response = client.get("/api/stocks/")
        data = response.json()
        assert data["total"] == len(data["stocks"])


# =========================================================
# TEST — GET /api/stocks/{symbol}
# =========================================================
class TestGetStock:

    def test_get_existing_stock(self, client: TestClient):
        response = client.get("/api/stocks/AAPL")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert data["company_name"] == "Apple Inc."

    def test_get_stock_case_insensitive(self, client: TestClient):
        response = client.get("/api/stocks/aapl")
        assert response.status_code == 200
        assert response.json()["symbol"] == "AAPL"

    def test_get_nonexistent_stock_returns_404(self, client: TestClient):
        response = client.get("/api/stocks/FAKESYMBOL")
        assert response.status_code == 404

        # ── FIXED ────────────────────────────────────────
        # error_handler.py returns "message" not "detail"
        # {"error": "not_found", "message": "...", "status_code": 404}
        assert "not found" in response.json()["message"].lower()


# =========================================================
# TEST — POST /api/stocks
# =========================================================
class TestCreateStock:

    def test_create_stock_success(self, client: TestClient):
        new_stock = {
            "symbol": "TEST",
            "company_name": "Test Company Inc.",
            "sector": "Technology",
            "industry": "Software"
        }
        response = client.post("/api/stocks/", json=new_stock)

        # ── FIXED ────────────────────────────────────────
        # cleanup_test_stocks fixture deleted TEST before
        # this test runs so we get 201 not 409
        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "TEST"
        assert data["company_name"] == "Test Company Inc."
        assert "id" in data
        assert "created_at" in data

    def test_create_duplicate_stock_returns_409(self, client: TestClient):
        duplicate = {
            "symbol": "AAPL",
            "company_name": "Apple Inc."
        }
        response = client.post("/api/stocks/", json=duplicate)
        assert response.status_code == 409

        # ── FIXED ────────────────────────────────────────
        # error_handler.py returns "message" not "detail"
        assert "already exists" in response.json()["message"].lower()

    def test_create_stock_lowercase_symbol_auto_uppercased(
        self, client: TestClient
    ):
        stock = {
            "symbol": "tsla",
            "company_name": "Tesla Inc."
        }
        response = client.post("/api/stocks/", json=stock)

        # ── FIXED ────────────────────────────────────────
        # cleanup_test_stocks deleted TSLA before this runs
        assert response.status_code == 201
        assert response.json()["symbol"] == "TSLA"

    def test_create_stock_missing_required_field(self, client: TestClient):
        incomplete = {"symbol": "INCOMPLETE"}
        response = client.post("/api/stocks/", json=incomplete)
        assert response.status_code == 422


# =========================================================
# TEST — PATCH /api/stocks/{symbol}
# =========================================================
class TestUpdateStock:

    def test_update_stock_sector(self, client: TestClient):
        update = {"sector": "Big Tech"}
        response = client.patch("/api/stocks/MSFT", json=update)
        assert response.status_code == 200
        assert response.json()["sector"] == "Big Tech"
        assert response.json()["company_name"] == "Microsoft Corporation"

    def test_update_nonexistent_stock(self, client: TestClient):
        response = client.patch(
            "/api/stocks/DOESNOTEXIST",
            json={"sector": "Technology"}
        )
        assert response.status_code == 404


# =========================================================
# TEST — DELETE /api/stocks/{symbol}
# =========================================================
class TestDeleteStock:

    def test_soft_delete_stock(self, client: TestClient):
        # TEST was created by TestCreateStock above
        get_response = client.get("/api/stocks/TEST")
        assert get_response.status_code == 200

        delete_response = client.delete("/api/stocks/TEST")
        assert delete_response.status_code == 200
        assert "deactivated" in delete_response.json()["message"].lower()

        # Should not appear in active list
        list_response = client.get("/api/stocks/")
        symbols = [s["symbol"] for s in list_response.json()["stocks"]]
        assert "TEST" not in symbols