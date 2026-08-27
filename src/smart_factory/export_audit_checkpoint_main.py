"""Export a signed checkpoint after verifying the complete database audit chain."""

import logging
from pathlib import Path

from smart_factory.config import AuditCheckpointSettings, Settings
from smart_factory.infrastructure.audit.checkpoint import (
    AuditCheckpointError,
    create_signed_checkpoint,
    write_signed_checkpoint,
)
from smart_factory.infrastructure.database.operator_audit import PsycopgOperatorAuditTrail
from smart_factory.infrastructure.ml.artifact_signing import ArtifactSigner
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(settings: Settings, checkpoint_settings: AuditCheckpointSettings) -> None:
    private_key_path = checkpoint_settings.private_key_path
    if private_key_path is None:
        raise ValueError("audit checkpoint export requires a private key")
    trail = PsycopgOperatorAuditTrail(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    try:
        trail.open(timeout=settings.database_connect_timeout_seconds)
        verification = trail.verify()
    finally:
        trail.close()
    if not verification.valid:
        raise AuditCheckpointError(
            f"operator audit chain invalid at sequence {verification.invalid_sequence_number}"
        )
    public_key_path = Path(checkpoint_settings.public_key_path)
    envelope = create_signed_checkpoint(
        verification,
        chain_id=checkpoint_settings.chain_id,
        signer=ArtifactSigner.from_private_key_file(Path(private_key_path)),
        public_key_path=public_key_path,
    )
    output_path = Path(checkpoint_settings.checkpoint_path)
    write_signed_checkpoint(output_path, envelope)
    LOGGER.info(
        "operator_audit_checkpoint_exported",
        extra={
            "chain_id": envelope.checkpoint.chain_id,
            "checkpoint_id": str(envelope.checkpoint.checkpoint_id),
            "event_count": envelope.checkpoint.event_count,
            "head_hash": envelope.checkpoint.head_hash,
            "key_id": envelope.checkpoint.key_id,
            "checkpoint_path": str(output_path),
        },
    )


def main() -> None:
    settings = Settings.from_env()
    checkpoint_settings = AuditCheckpointSettings.from_env(require_private_key=True)
    configure_logging(settings.log_level)
    run(settings, checkpoint_settings)


if __name__ == "__main__":
    main()
