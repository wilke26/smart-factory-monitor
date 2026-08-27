from pathlib import Path
from unittest.mock import Mock, call
from uuid import UUID

import pytest

from smart_factory.application.services.model_promotion import (
    ModelPromotionError,
    ModelPromotionService,
    ModelRollbackService,
    PromotionCandidate,
)
from smart_factory.domain.model_registry import ModelRegistryEntry, ModelRegistryManifest
from smart_factory.domain.operator_audit import OperatorActionOutcome, OperatorAuditContext


def candidates() -> tuple[PromotionCandidate, ...]:
    return (
        PromotionCandidate("press-01", "model-1", "a" * 64, Path("/candidates/one")),
        PromotionCandidate("press-02", "model-2", "b" * 64, Path("/candidates/two")),
    )


def audit_context() -> OperatorAuditContext:
    return OperatorAuditContext(
        actor="release-bot",
        reason="ticket-123",
        correlation_id=UUID("11111111-1111-1111-1111-111111111111"),
    )


def manifest() -> ModelRegistryManifest:
    return ModelRegistryManifest(
        generation_id=UUID("22222222-2222-2222-2222-222222222222"),
        previous_generation_id=UUID("33333333-3333-3333-3333-333333333333"),
        entries=(
            ModelRegistryEntry(machine_id="press-01", model_id="model-1", artifact_sha256="a" * 64),
        ),
    )


def test_publishes_complete_batch_only_after_every_candidate_passed() -> None:
    approvals = Mock()
    approvals.has_passed.return_value = True
    registry = Mock()
    registry.publish.return_value = manifest()
    audit_trail = Mock()
    service = ModelPromotionService(approvals, registry, audit_trail, audit_context())
    batch = candidates()

    result = service.promote(batch)

    assert result is registry.publish.return_value
    assert approvals.has_passed.call_args_list == [
        call(machine_id="press-01", model_id="model-1", artifact_sha256="a" * 64),
        call(machine_id="press-02", model_id="model-2", artifact_sha256="b" * 64),
    ]
    registry.publish.assert_called_once_with(batch)
    assert [item.args[0].outcome for item in audit_trail.append.call_args_list] == [
        OperatorActionOutcome.STARTED,
        OperatorActionOutcome.SUCCEEDED,
    ]


def test_rejects_entire_batch_when_exact_artifact_has_no_passed_evaluation() -> None:
    approvals = Mock()
    approvals.has_passed.side_effect = [True, False]
    registry = Mock()
    audit_trail = Mock()

    with pytest.raises(ModelPromotionError, match="press-02"):
        ModelPromotionService(approvals, registry, audit_trail, audit_context()).promote(
            candidates()
        )

    registry.publish.assert_not_called()
    events = [item.args[0] for item in audit_trail.append.call_args_list]
    assert [event.outcome for event in events] == [
        OperatorActionOutcome.STARTED,
        OperatorActionOutcome.FAILED,
    ]
    assert events[-1].error_type == "ModelPromotionError"


def test_does_not_publish_when_initial_audit_write_fails() -> None:
    approvals = Mock()
    registry = Mock()
    audit_trail = Mock()
    audit_trail.append.side_effect = RuntimeError("audit unavailable")

    with pytest.raises(RuntimeError, match="audit unavailable"):
        ModelPromotionService(approvals, registry, audit_trail, audit_context()).promote(
            candidates()
        )

    approvals.has_passed.assert_not_called()
    registry.publish.assert_not_called()


def test_audits_explicit_rollback_transition() -> None:
    registry = Mock()
    registry.rollback.return_value = manifest()
    audit_trail = Mock()
    target = UUID("44444444-4444-4444-4444-444444444444")

    result = ModelRollbackService(registry, audit_trail, audit_context()).rollback(target)

    assert result is registry.rollback.return_value
    registry.rollback.assert_called_once_with(target)
    events = [item.args[0] for item in audit_trail.append.call_args_list]
    assert [event.outcome for event in events] == [
        OperatorActionOutcome.STARTED,
        OperatorActionOutcome.SUCCEEDED,
    ]
    assert dict(events[-1].resulting_state)["source_generation_id"] == str(target)
