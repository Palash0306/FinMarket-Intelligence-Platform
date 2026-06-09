# =========================================================
# ANOMALIES API
# =========================================================
#
# Exposes detected anomalies via REST endpoints.
#
# Connection chain:
# RDS anomalies table (written by detector.py)
#       ↓ queried by THIS FILE
#       ↓ shaped by schemas/anomaly.py
#       ↓ returned to
# Browser / Streamlit dashboard (Phase 5 alerts)
# Phase 4 RAG agent ("any anomalies today?")

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.anomaly import Anomaly
from app.schemas.anomaly import AnomalyListResponse, AnomalyResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/anomalies",
    tags=["Anomalies"]
)


@router.get(
    "/{symbol}",
    response_model=AnomalyListResponse,
    summary="Get anomalies for a stock"
)
def get_anomalies_for_symbol(
    symbol: str,
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db)
):
    """
    Returns detected anomalies for a symbol.
    Used by Phase 5 dashboard alerts section.
    """
    anomalies = db.query(Anomaly).filter(
        Anomaly.symbol == symbol.upper()
    ).order_by(
        Anomaly.detected_at.desc()
    ).limit(50).all()

    return AnomalyListResponse(
        symbol    = symbol.upper(),
        total     = len(anomalies),
        anomalies = anomalies
    )


@router.get(
    "/",
    response_model=AnomalyListResponse,
    summary="Get all recent anomalies"
)
def get_all_anomalies(
    severity: str = Query(default=None),
    db: Session   = Depends(get_db)
):
    """
    Returns all recent anomalies across all stocks.
    Used by Phase 5 dashboard alerts feed.
    """
    query = db.query(Anomaly).order_by(
        Anomaly.detected_at.desc()
    )

    if severity:
        query = query.filter(Anomaly.severity == severity)

    anomalies = query.limit(100).all()

    return AnomalyListResponse(
        symbol    = None,
        total     = len(anomalies),
        anomalies = anomalies
    )