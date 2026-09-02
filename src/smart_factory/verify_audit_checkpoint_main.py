"""Verify a portable audit checkpoint without database access."""

import logging
import os
from pathlib import Path

from smart_factory.config import AuditCheckpointSettings
from smart_factory.infrastructure.audit.checkpoint import (
    load_signed_checkpoint,
    verify_signed_checkpoint,
)
from smart_factory.infrastructure.audit.keyring import AuditAttestationKeyring
from smart_factory.infrastructure.ml.artifact_signing import ArtifactVerifier
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(settings: AuditCheckpointSettings) -> None:
    if settings.keyring_path is None:
        raise ValueError("audit checkpoint verification requires a trusted keyring")
    envelope = load_signed_checkpoint(Path(settings.checkpoint_path))
    public_key_path = AuditAttestationKeyring(
        Path(settings.keyring_path),
        settings.resolve_trusted_root_key_id(),
    ).resolve_trusted_key(
        envelope.checkpoint.key_id,
        expected_chain_id=settings.chain_id,
    )
    checkpoint = verify_signed_checkpoint(
        envelope,
        verifier=ArtifactVerifier.from_public_key_file(public_key_path),
        public_key_path=public_key_path,
        expected_chain_id=settings.chain_id,
    )
    LOGGER.info(
        "operator_audit_checkpoint_verified",
        extra={
            "chain_id": checkpoint.chain_id,
            "checkpoint_id": str(checkpoint.checkpoint_id),
            "event_count": checkpoint.event_count,
            "head_hash": checkpoint.head_hash,
            "key_id": checkpoint.key_id,
        },
    )


def main() -> None:
    configure_logging(os.getenv("LOG_LEVEL", "INFO").upper())
    run(
        AuditCheckpointSettings.from_env(
            require_private_key=False,
            require_keyring=True,
        )
    )


if __name__ == "__main__":
    main()
