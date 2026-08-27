"""Console entry point for audit-attestation key initialization."""

import logging
import os
from pathlib import Path

from smart_factory.infrastructure.audit.keyring import AuditAttestationKeyring
from smart_factory.infrastructure.ml.artifact_signing import ensure_ed25519_key_pair
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def main() -> None:
    configure_logging(os.getenv("LOG_LEVEL", "INFO").upper())
    private_path = Path(
        os.getenv(
            "AUDIT_ATTESTATION_PRIVATE_KEY_PATH",
            "/run/audit-attestation/private/private.pem",
        )
    )
    public_path = Path(
        os.getenv(
            "AUDIT_ATTESTATION_PUBLIC_KEY_PATH",
            "/run/audit-attestation/public/public.pem",
        )
    )
    created = ensure_ed25519_key_pair(private_path, public_path)
    keyring_path = Path(
        os.getenv("AUDIT_ATTESTATION_KEYRING_PATH", "/run/audit-attestation/public/keyring")
    )
    root_key_id_path = Path(
        os.getenv(
            "AUDIT_ATTESTATION_ROOT_KEY_ID_PATH",
            "/run/audit-attestation/public/trusted-root-key-id",
        )
    )
    key_id = AuditAttestationKeyring(keyring_path, root_key_id_path).initialize(public_path)
    LOGGER.info(
        "audit_attestation_key_ready",
        extra={
            "key_created": created,
            "key_id": key_id,
            "public_key_path": str(public_path),
        },
    )


if __name__ == "__main__":
    main()
