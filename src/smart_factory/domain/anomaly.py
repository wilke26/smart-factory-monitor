"""Anomaly findings produced from validated telemetry."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class AnomalySeverity(StrEnum):
    """Operational priority assigned to a detector finding."""

    MEDIUM = "medium"
    HIGH = "high"


class AnomalyFinding(BaseModel):
    """One immutable detector result with persisted decision evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule_id: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    severity: AnomalySeverity
    metric: str
    observed_value: float
    threshold: float
    comparison: str
    message: str
