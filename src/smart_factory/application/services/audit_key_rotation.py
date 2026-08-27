"""Audited orchestration for attestation-key rotation."""

from smart_factory.application.ports.audit_keyring import AuditAttestationKeyRotator
from smart_factory.application.ports.operator_audit import OperatorAuditTrail
from smart_factory.domain.audit_keyring import AuditKeyRotationResult
from smart_factory.domain.operator_audit import (
    OperatorAction,
    OperatorActionOutcome,
    OperatorAuditContext,
    OperatorAuditEvent,
)


class AuditAttestationKeyRotationService:
    def __init__(
        self,
        rotator: AuditAttestationKeyRotator,
        audit_trail: OperatorAuditTrail,
    ) -> None:
        self._rotator = rotator
        self._audit_trail = audit_trail

    def rotate(self, context: OperatorAuditContext) -> AuditKeyRotationResult:
        previous_key_id = self._rotator.current_key_id()
        previous_state = (("key_id", previous_key_id),)
        self._audit_trail.append(
            OperatorAuditEvent.create(
                context,
                action=OperatorAction.AUDIT_ATTESTATION_KEY_ROTATION,
                outcome=OperatorActionOutcome.STARTED,
                previous_state=previous_state,
            )
        )
        try:
            result = self._rotator.rotate()
        except Exception as error:
            self._audit_trail.append(
                OperatorAuditEvent.create(
                    context,
                    action=OperatorAction.AUDIT_ATTESTATION_KEY_ROTATION,
                    outcome=OperatorActionOutcome.FAILED,
                    previous_state=previous_state,
                    error_type=type(error).__name__,
                )
            )
            raise
        self._audit_trail.append(
            OperatorAuditEvent.create(
                context,
                action=OperatorAction.AUDIT_ATTESTATION_KEY_ROTATION,
                outcome=OperatorActionOutcome.SUCCEEDED,
                previous_state=previous_state,
                resulting_state=(
                    ("key_id", result.new_key_id),
                    ("transition_id", str(result.transition_id)),
                ),
            )
        )
        return result
