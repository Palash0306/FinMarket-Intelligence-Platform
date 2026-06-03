# path: tests/conftest.py

import pytest
import os

# ── Set test environment BEFORE importing the app ────────
#
# These must be set BEFORE any app imports happen.
# config.py reads .env on first import — if we set
# these after import, it's too late.
#
# TESTING=true → tells main.py lifespan to skip consumers
# Use localhost for services not running locally
os.environ["TESTING"] = "true"
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# ── NOW import the app ────────────────────────────────────
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models.stock import Stock


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_stocks():
    """
    Removes test symbols from RDS before and after tests.
    Prevents 409 conflicts from previous test runs.
    """
    db = SessionLocal()
    try:
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

    yield

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