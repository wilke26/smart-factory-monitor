"""Infrastructure for externally retained operator-audit checkpoints."""

from smart_factory.infrastructure.audit.checkpoint import (
    AuditCheckpointError,
    create_signed_checkpoint,
    load_signed_checkpoint,
    verify_signed_checkpoint,
    write_signed_checkpoint,
)
from smart_factory.infrastructure.audit.keyring import (
    AuditAttestationKeyring,
    FilesystemAuditAttestationKeyRotator,
)

__all__ = [
    "AuditAttestationKeyring",
    "AuditCheckpointError",
    "FilesystemAuditAttestationKeyRotator",
    "create_signed_checkpoint",
    "load_signed_checkpoint",
    "verify_signed_checkpoint",
    "write_signed_checkpoint",
]
