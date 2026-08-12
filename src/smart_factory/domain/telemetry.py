"""Validated data contract shared by telemetry producers and consumers."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

MachineId = Annotated[
    str,
    Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=3, max_length=64),
]


class TelemetryReading(BaseModel):
    """One immutable and strictly validated machine measurement."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    machine_id: MachineId
    timestamp: datetime
    temperature_c: Annotated[float, Field(ge=-50.0, le=250.0, allow_inf_nan=False)]
    vibration_mm_s: Annotated[float, Field(ge=0.0, le=100.0, allow_inf_nan=False)]
    power_kw: Annotated[float, Field(ge=0.0, le=500.0, allow_inf_nan=False)]
    production_rate: Annotated[int, Field(ge=0, le=10_000)]

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Reject ambiguous local timestamps at the system boundary."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value

    def to_mqtt_payload(self) -> bytes:
        """Serialize to compact UTF-8 JSON using ISO-8601 timestamps."""
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_mqtt_payload(cls, payload: bytes) -> Self:
        """Decode and strictly validate an untrusted MQTT JSON payload."""
        return cls.model_validate_json(payload, strict=True)


# Preserve the public v0.1 import while naming the application input explicitly.
Telemetry = TelemetryReading
