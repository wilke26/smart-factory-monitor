"""Outbound ports for controlled model-registry publication."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from smart_factory.domain.model_registry import ModelRegistryManifest


class ModelPromotionCandidate(Protocol):
    @property
    def machine_id(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def artifact_sha256(self) -> str: ...

    @property
    def artifact_path(self) -> Path: ...


class ModelRegistryPublisher(Protocol):
    def publish(
        self,
        candidates: Sequence[ModelPromotionCandidate],
    ) -> ModelRegistryManifest: ...

    def rollback(self, generation_id: UUID) -> ModelRegistryManifest: ...
