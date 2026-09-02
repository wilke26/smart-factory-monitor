"""Rotate the audit-attestation key with durable operator evidence."""

import logging
import os
import re
from pathlib import Path

from smart_factory.application.services.audit_key_rotation import (
    AuditAttestationKeyRotationService,
)
from smart_factory.config import AuditCheckpointSettings, OperatorAuditSettings, Settings
from smart_factory.infrastructure.audit.keyring import (
    AuditAttestationKeyring,
    FilesystemAuditAttestationKeyRotator,
)
from smart_factory.infrastructure.database.operator_audit import PsycopgOperatorAuditTrail
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)
KEY_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def run(
    settings: Settings,
    checkpoint_settings: AuditCheckpointSettings,
    audit_settings: OperatorAuditSettings,
    expected_active_key_id: str,
) -> None:
    if checkpoint_settings.private_key_path is None or checkpoint_settings.keyring_path is None:
        raise ValueError("audit key rotation requires private key and trusted keyring")
    trail = PsycopgOperatorAuditTrail(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    try:
        trail.open(timeout=settings.database_connect_timeout_seconds)
        result = AuditAttestationKeyRotationService(
            FilesystemAuditAttestationKeyRotator(
                chain_id=checkpoint_settings.chain_id,
                private_key_path=Path(checkpoint_settings.private_key_path),
                public_key_path=Path(checkpoint_settings.public_key_path),
                keyring=AuditAttestationKeyring(
                    Path(checkpoint_settings.keyring_path),
                    checkpoint_settings.resolve_trusted_root_key_id(),
                ),
            ),
            trail,
        ).rotate(
            audit_settings.context,
            expected_active_key_id=expected_active_key_id,
        )
    finally:
        trail.close()
    LOGGER.info(
        "audit_attestation_key_rotated",
        extra={
            "transition_id": str(result.transition_id),
            "previous_key_id": result.previous_key_id,
            "new_key_id": result.new_key_id,
            "actor": audit_settings.actor,
            "correlation_id": str(audit_settings.correlation_id),
        },
    )


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    expected_active_key_id = os.getenv("AUDIT_ATTESTATION_EXPECTED_ACTIVE_KEY_ID", "").strip()
    if not KEY_ID_PATTERN.fullmatch(expected_active_key_id):
        raise ValueError("AUDIT_ATTESTATION_EXPECTED_ACTIVE_KEY_ID must be 64 lowercase hex")
    run(
        settings,
        AuditCheckpointSettings.from_env(
            require_private_key=True,
            require_keyring=True,
        ),
        OperatorAuditSettings.from_env(),
        expected_active_key_id,
    )


if __name__ == "__main__":
    main()
