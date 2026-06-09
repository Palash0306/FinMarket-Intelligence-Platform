from pydantic import BaseModel
from typing import Optional


class AnomalyResponse(BaseModel):
    id:             int
    symbol:         str
    detected_at:    str
    anomaly_type:   str
    z_score:        float
    actual_value:   float
    expected_value: float
    description:    Optional[str] = None
    severity:       str
    is_alerted:     bool

    model_config = {"from_attributes": True}


class AnomalyListResponse(BaseModel):
    symbol:    Optional[str] = None
    total:     int
    anomalies: list[AnomalyResponse]