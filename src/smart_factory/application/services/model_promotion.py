"""Approval-gated model promotion independent of filesystem publication details."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from smart_factory.application.ports.model_evaluation import ModelApprovalReader
from smart_factory.application.ports.model_registry import ModelRegistryPublisher
from smart_factory.application.ports.operator_audit import OperatorAuditTrail
from smart_factory.domain.model_registry import ModelRegistryManifest
from smart_factory.domain.operator_audit import (
    AuditState,
    OperatorAction,
    OperatorActionOutcome,
    OperatorAuditContext,
    OperatorAuditEvent,
)


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
        audit_trail: OperatorAuditTrail,
        audit_context: OperatorAuditContext,
    ) -> None:
        self._approvals = approvals
        self._registry = registry
        self._audit_trail = audit_trail
        self._audit_context = audit_context

    def promote(
        self,
        candidates: tuple[PromotionCandidate, ...],
    ) -> ModelRegistryManifest:
        intended_state = (
            (
                "candidate_artifacts",
                tuple(
                    f"{candidate.machine_id}:{candidate.model_id}:{candidate.artifact_sha256}"
                    for candidate in candidates
                ),
            ),
        )
        self._record(
            action=OperatorAction.MODEL_PROMOTION,
            outcome=OperatorActionOutcome.STARTED,
            resulting_state=intended_state,
        )
        try:
            for candidate in candidates:
                if not self._approvals.has_passed(
                    machine_id=candidate.machine_id,
                    model_id=candidate.model_id,
                    artifact_sha256=candidate.artifact_sha256,
                ):
                    raise ModelPromotionError(
                        f"no passed evaluation for candidate machine {candidate.machine_id}"
                    )
            manifest = self._registry.publish(candidates)
        except Exception as error:
            self._record(
                action=OperatorAction.MODEL_PROMOTION,
                outcome=OperatorActionOutcome.FAILED,
                resulting_state=intended_state,
                error_type=type(error).__name__,
            )
            raise
        self._record_manifest_transition(
            OperatorAction.MODEL_PROMOTION,
            manifest,
        )
        return manifest

    def _record_manifest_transition(
        self,
        action: OperatorAction,
        manifest: ModelRegistryManifest,
        *,
        source_generation_id: UUID | None = None,
    ) -> None:
        previous_generation_id = manifest.previous_generation_id
        previous_state = (
            (
                "generation_id",
                str(previous_generation_id) if previous_generation_id is not None else None,
            ),
        )
        resulting_state: AuditState = (
            ("generation_id", str(manifest.generation_id)),
            ("machine_ids", tuple(entry.machine_id for entry in manifest.entries)),
        )
        if source_generation_id is not None:
            resulting_state += (("source_generation_id", str(source_generation_id)),)
        self._record(
            action=action,
            outcome=OperatorActionOutcome.SUCCEEDED,
            previous_state=previous_state,
            resulting_state=resulting_state,
        )

    def _record(
        self,
        *,
        action: OperatorAction,
        outcome: OperatorActionOutcome,
        previous_state: AuditState = (),
        resulting_state: AuditState = (),
        error_type: str | None = None,
    ) -> None:
        self._audit_trail.append(
            OperatorAuditEvent.create(
                self._audit_context,
                action=action,
                outcome=outcome,
                previous_state=previous_state,
                resulting_state=resulting_state,
                error_type=error_type,
            )
        )


class ModelRollbackService:
    """Audit an explicit registry rollback before and after filesystem publication."""

    def __init__(
        self,
        registry: ModelRegistryPublisher,
        audit_trail: OperatorAuditTrail,
        audit_context: OperatorAuditContext,
    ) -> None:
        self._registry = registry
        self._audit_trail = audit_trail
        self._audit_context = audit_context

    def rollback(self, generation_id: UUID) -> ModelRegistryManifest:
        target_state = (("source_generation_id", str(generation_id)),)
        self._record(OperatorActionOutcome.STARTED, target_state)
        try:
            manifest = self._registry.rollback(generation_id)
        except Exception as error:
            self._record(
                OperatorActionOutcome.FAILED,
                target_state,
                error_type=type(error).__name__,
            )
            raise
        previous_generation_id = manifest.previous_generation_id
        self._audit_trail.append(
            OperatorAuditEvent.create(
                self._audit_context,
                action=OperatorAction.MODEL_ROLLBACK,
                outcome=OperatorActionOutcome.SUCCEEDED,
                previous_state=(
                    (
                        "generation_id",
                        str(previous_generation_id) if previous_generation_id is not None else None,
                    ),
                ),
                resulting_state=(
                    ("generation_id", str(manifest.generation_id)),
                    ("source_generation_id", str(generation_id)),
                    ("machine_ids", tuple(entry.machine_id for entry in manifest.entries)),
                ),
            )
        )
        return manifest

    def _record(
        self,
        outcome: OperatorActionOutcome,
        resulting_state: AuditState,
        *,
        error_type: str | None = None,
    ) -> None:
        self._audit_trail.append(
            OperatorAuditEvent.create(
                self._audit_context,
                action=OperatorAction.MODEL_ROLLBACK,
                outcome=outcome,
                resulting_state=resulting_state,
                error_type=error_type,
            )
        )
