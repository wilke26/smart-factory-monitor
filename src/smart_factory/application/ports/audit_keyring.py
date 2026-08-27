"""Port for controlled audit-attestation key rotation."""

from typing import Protocol

from smart_factory.domain.audit_keyring import AuditKeyRotationResult


class AuditAttestationKeyRotator(Protocol):
    def current_key_id(self) -> str: ...

    def rotate(self) -> AuditKeyRotationResult: ...
