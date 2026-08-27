from unittest.mock import Mock
from uuid import UUID

import pytest

from smart_factory.application.services.audit_key_rotation import (
    AuditAttestationKeyRotationService,
)
from smart_factory.domain.audit_keyring import AuditKeyRotationResult
from smart_factory.domain.operator_audit import OperatorActionOutcome, OperatorAuditContext


def context() -> OperatorAuditContext:
    return OperatorAuditContext(
        actor="security-operator",
        reason="ticket-456",
        correlation_id=UUID("11111111-1111-1111-1111-111111111111"),
    )


def test_audits_started_and_successful_rotation() -> None:
    rotator = Mock()
    rotator.current_key_id.return_value = "a" * 64
    rotator.rotate.return_value = AuditKeyRotationResult(
        transition_id=UUID("22222222-2222-2222-2222-222222222222"),
        previous_key_id="a" * 64,
        new_key_id="b" * 64,
    )
    trail = Mock()

    result = AuditAttestationKeyRotationService(rotator, trail).rotate(context())

    assert result.new_key_id == "b" * 64
    events = [call.args[0] for call in trail.append.call_args_list]
    assert [event.outcome for event in events] == [
        OperatorActionOutcome.STARTED,
        OperatorActionOutcome.SUCCEEDED,
    ]
    assert dict(events[1].resulting_state) == {
        "key_id": "b" * 64,
        "transition_id": "22222222-2222-2222-2222-222222222222",
    }


def test_audits_failed_rotation_and_reraises() -> None:
    rotator = Mock()
    rotator.current_key_id.return_value = "a" * 64
    rotator.rotate.side_effect = OSError("disk full")
    trail = Mock()

    with pytest.raises(OSError, match="disk full"):
        AuditAttestationKeyRotationService(rotator, trail).rotate(context())

    events = [call.args[0] for call in trail.append.call_args_list]
    assert events[-1].outcome is OperatorActionOutcome.FAILED
    assert events[-1].error_type == "OSError"
