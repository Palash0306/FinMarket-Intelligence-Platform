# path: tests/conftest.py

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    """
    Creates a test client for the FastAPI app.
    scope="module" means one client is shared across all tests in a file
    — faster than creating a new one for each test.
    """
    with TestClient(app) as c:
        yield c