"""Approval-gated model promotion independent of filesystem publication details."""

from dataclasses import dataclass
from pathlib import Path

from smart_factory.application.ports.model_evaluation import ModelApprovalReader
from smart_factory.application.ports.model_registry import ModelRegistryPublisher
from smart_factory.domain.model_registry import ModelRegistryManifest


class ModelPromotionError(RuntimeError):
    """A candidate cannot be promoted through the controlled registry path."""


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    machine_id: str
    model_id: str
    artifact_sha256: str
    artifact_path: Path


class ModelPromotionService:
    def __init__(
        self,
        approvals: ModelApprovalReader,
        registry: ModelRegistryPublisher,
    ) -> None:
        self._approvals = approvals
        self._registry = registry

    def promote(
        self,
        candidates: tuple[PromotionCandidate, ...],
    ) -> ModelRegistryManifest:
        for candidate in candidates:
            if not self._approvals.has_passed(
                machine_id=candidate.machine_id,
                model_id=candidate.model_id,
                artifact_sha256=candidate.artifact_sha256,
            ):
                raise ModelPromotionError(
                    f"no passed evaluation for candidate machine {candidate.machine_id}"
                )
        return self._registry.publish(candidates)
