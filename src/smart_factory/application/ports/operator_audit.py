"""Outbound port for append-only privileged-operation evidence."""

from typing import Protocol

from smart_factory.domain.operator_audit import AuditChainVerification, OperatorAuditEvent


class OperatorAuditTrail(Protocol):
    def append(self, event: OperatorAuditEvent) -> None: ...

    def verify(self) -> AuditChainVerification: ...
