"""Explainable anomaly findings produced from validated telemetry."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class AnomalySeverity(StrEnum):
    """Operational priority assigned by a deterministic rule."""

    MEDIUM = "medium"
    HIGH = "high"


class AnomalyFinding(BaseModel):
    """One immutable explanation of a violated telemetry rule."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule_id: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    severity: AnomalySeverity
    metric: str
    observed_value: float
    threshold: float
    comparison: str
    message: str
