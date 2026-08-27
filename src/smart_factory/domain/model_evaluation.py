"""Durable evidence produced by offline model-quality evaluation."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from smart_factory.domain.telemetry import MachineId

FeaturePsi = tuple[
    Annotated[str, Field(min_length=1, max_length=64)],
    Annotated[float, Field(ge=0.0, allow_inf_nan=False)],
]
FailedGate = Literal["minimum_samples", "maximum_anomaly_rate", "maximum_feature_psi"]
ArtifactSha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ModelEvaluationEvidence(BaseModel):
    """Immutable audit record for one signed model evaluation run."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evaluation_id: UUID = Field(default_factory=uuid4)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_id: Annotated[str, Field(min_length=1, max_length=255)]
    artifact_sha256: ArtifactSha256
    machine_id: MachineId
    training_window_end: datetime
    sample_count: Annotated[int, Field(ge=0)]
    anomaly_rate: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    feature_psi: tuple[FeaturePsi, ...]
    maximum_feature_psi: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    passed: bool
    failed_gates: tuple[FailedGate, ...]

    @field_validator("evaluated_at", "training_window_end")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("model evaluation timestamps must include a UTC offset")
        return value

    @model_validator(mode="after")
    def evidence_must_be_consistent(self) -> Self:
        feature_names = [name for name, _ in self.feature_psi]
        if len(feature_names) != len(set(feature_names)):
            raise ValueError("model evaluation feature names must be unique")
        expected_maximum = max((value for _, value in self.feature_psi), default=0.0)
        if self.maximum_feature_psi != expected_maximum:
            raise ValueError("maximum_feature_psi must match feature_psi")
        if self.passed != (not self.failed_gates):
            raise ValueError("passed must agree with failed_gates")
        if self.training_window_end > self.evaluated_at:
            raise ValueError("training_window_end must not be after evaluated_at")
        return self
