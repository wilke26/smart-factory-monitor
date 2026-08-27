from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from smart_factory.domain.operator_audit import (
    OperatorAction,
    OperatorActionOutcome,
    OperatorAuditContext,
    OperatorAuditEvent,
)


def context() -> OperatorAuditContext:
    return OperatorAuditContext(
        actor="release-bot",
        reason="ticket-123",
        correlation_id=UUID("11111111-1111-1111-1111-111111111111"),
    )


def test_creates_immutable_failed_event_with_explicit_error_type() -> None:
    event = OperatorAuditEvent.create(
        context(),
        action=OperatorAction.MODEL_PROMOTION,
        outcome=OperatorActionOutcome.FAILED,
        resulting_state=(("machine_ids", ("press-01", "press-02")),),
        error_type="ModelPromotionError",
    )

    assert event.actor == "release-bot"
    assert event.error_type == "ModelPromotionError"
    assert event.occurred_at.tzinfo is not None

    with pytest.raises(ValidationError):
        event.actor = "other"  # type: ignore[misc]


def test_rejects_error_type_that_does_not_match_outcome() -> None:
    with pytest.raises(ValidationError, match="failed audit events require"):
        OperatorAuditEvent(
            event_id=UUID("22222222-2222-2222-2222-222222222222"),
            occurred_at=datetime(2026, 8, 27, tzinfo=UTC),
            actor="release-bot",
            reason="ticket-123",
            correlation_id=context().correlation_id,
            action=OperatorAction.MODEL_ROLLBACK,
            outcome=OperatorActionOutcome.FAILED,
        )


def test_rejects_duplicate_state_keys() -> None:
    with pytest.raises(ValidationError, match="state keys must be unique"):
        OperatorAuditEvent.create(
            context(),
            action=OperatorAction.MODEL_PROMOTION,
            outcome=OperatorActionOutcome.STARTED,
            resulting_state=(("generation_id", "one"), ("generation_id", "two")),
        )
