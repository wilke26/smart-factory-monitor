"""Transport-neutral anomaly alert contract."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from smart_factory.domain.anomaly import AnomalySeverity
from smart_factory.domain.telemetry import MachineId


class AnomalyAlert(BaseModel):
    """Immutable evidence delivered to an external alert destination."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: UUID
    machine_id: MachineId
    recorded_at: datetime
    rule_id: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    severity: AnomalySeverity
    metric: str
    observed_value: float
    threshold: float
    comparison: Literal[">", "<"]
    message: str

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include a UTC offset")
        return value

    @classmethod
    def from_json(cls, payload: bytes) -> Self:
        return cls.model_validate_json(payload, strict=True)
