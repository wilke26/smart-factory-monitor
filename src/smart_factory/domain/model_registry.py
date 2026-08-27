"""Versioned model-registry contracts used by promotion and inference."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from smart_factory.domain.model_evaluation import ArtifactSha256
from smart_factory.domain.telemetry import MachineId


class ModelRegistryEntry(BaseModel):
    """One immutable model version referenced by an active generation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    machine_id: MachineId
    model_id: Annotated[str, Field(min_length=1, max_length=255)]
    artifact_sha256: ArtifactSha256


class ModelRegistryManifest(BaseModel):
    """Atomically replaceable pointer to one complete approved model set."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    generation_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previous_generation_id: UUID | None = None
    source_generation_id: UUID | None = None
    entries: tuple[ModelRegistryEntry, ...]

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registry manifest timestamp must include a UTC offset")
        return value

    @model_validator(mode="after")
    def entries_must_be_unique(self) -> Self:
        machine_ids = [entry.machine_id for entry in self.entries]
        if not machine_ids:
            raise ValueError("registry manifest must contain at least one model")
        if len(machine_ids) != len(set(machine_ids)):
            raise ValueError("registry manifest machine IDs must be unique")
        return self
