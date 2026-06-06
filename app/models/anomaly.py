# path: app/models/anomaly.py

# =========================================================
# ANOMALY MODEL
# =========================================================
#
# Stores detected anomalies — unusual price or volume events.
# One row = one anomaly event for one stock at one time.
#
# Connection chain:
# ClickHouse ohlcv (prices)
#       ↓ read by
# detector.py (statsmodels z-score analysis)
#       ↓ anomalies stored in
# THIS TABLE (anomalies)
#       ↓ read by
# api/anomalies.py → GET /api/anomalies/AAPL
# Phase 5 alerts → sends email/Slack when anomaly detected
# Phase 4 RAG agent → "any unusual moves today?"

from sqlalchemy import Integer, String, Float, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Anomaly(Base, TimestampMixin):
    """
    One detected anomaly event.

    Table: anomalies
    """

    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    symbol: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="Stock ticker"
    )

    # When this anomaly was detected
    detected_at: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="ISO timestamp when anomaly was detected"
    )

    # What type of anomaly
    # "price_spike"    = price moved unusually far
    # "volume_spike"   = trading volume unusually high
    # "price_crash"    = price dropped unusually fast
    anomaly_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="price_spike / volume_spike / price_crash"
    )

    # How unusual is this? (statistical measure)
    # z_score = how many standard deviations from the mean
    # z_score > 2.0  = unusual (95th percentile)
    # z_score > 3.0  = very unusual (99.7th percentile)
    z_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Standard deviations from mean — higher = more unusual"
    )

    # The actual value that triggered the anomaly
    actual_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="The price or volume that was anomalous"
    )

    # What was expected (the rolling average)
    expected_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="The expected normal value"
    )

    # Human-readable description
    # e.g. "AAPL price surged 8.3% (3.2σ above 30-day mean)"
    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Human-readable anomaly description"
    )

    # Severity for alerting (Phase 5)
    # "low" / "medium" / "high"
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="medium",
        comment="low / medium / high — used by Phase 5 alerts"
    )

    # Track if this anomaly has been sent as an alert
    # Phase 5 sets this True after sending notification
    is_alerted: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
        nullable=False,
        comment="True when Phase 5 has sent an alert for this"
    )

    __table_args__ = (
        Index(
            "ix_anomaly_symbol_detected",
            "symbol",
            "detected_at"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Anomaly {self.symbol} "
            f"{self.anomaly_type} "
            f"z={self.z_score:.2f}>"
        )