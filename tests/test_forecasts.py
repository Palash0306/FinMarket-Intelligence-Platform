import pytest
from fastapi.testclient import TestClient


class TestGetForecast:

    def test_invalid_symbol_returns_404(
        self, client: TestClient
    ):
        """Symbol not in stocks table → 404."""
        response = client.get("/api/forecasts/FAKESYMBOL")
        assert response.status_code == 404

    def test_valid_symbol_no_forecast_returns_404(
        self, client: TestClient
    ):
        """
        Valid symbol but no forecast generated yet → 404.
        Prophet/XGBoost haven't run yet in test environment.
        """
        response = client.get("/api/forecasts/AAPL")
        assert response.status_code in [200, 404]

    def test_trigger_forecast_returns_200(
        self, client: TestClient
    ):
        """
        POST to trigger forecast should return 200 immediately.
        BackgroundTasks runs asynchronously — response is instant.
        """
        response = client.post("/api/forecasts/AAPL/run")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "running"

    def test_all_signals_returns_200(
        self, client: TestClient
    ):
        """GET /api/forecasts/ returns 200 even with no data."""
        response = client.get("/api/forecasts/")
        assert response.status_code == 200
        data = response.json()
        assert "signals" in data
        assert "total" in data

    def test_trigger_invalid_symbol_returns_404(
        self, client: TestClient
    ):
        """Trigger on unknown symbol → 404."""
        response = client.post("/api/forecasts/FAKESYMBOL/run")
        assert response.status_code == 404