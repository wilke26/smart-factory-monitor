"""Console entry point for audit-attestation key initialization."""

import logging
import os
from pathlib import Path

from smart_factory.infrastructure.audit.checkpoint import public_key_id
from smart_factory.infrastructure.audit.keyring import AuditAttestationKeyring
from smart_factory.infrastructure.ml.artifact_signing import ensure_ed25519_key_pair
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def _boolean_environment(name: str) -> bool:
    value = os.getenv(name, "false").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


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
    chain_id = os.getenv("AUDIT_CHAIN_ID", "").strip() or None
    root_key_id_path = Path(
        os.getenv(
            "AUDIT_ATTESTATION_ROOT_KEY_ID_PATH",
            "/run/audit-attestation/public/trusted-root-key-id",
        )
    )
    key_id = public_key_id(public_path)
    configured_root_key_id = os.getenv("AUDIT_ATTESTATION_TRUSTED_ROOT_KEY_ID", "").strip()
    allow_colocated_root = _boolean_environment("AUDIT_ATTESTATION_ALLOW_COLOCATED_ROOT")
    if configured_root_key_id:
        trusted_root_key_id = configured_root_key_id
    elif allow_colocated_root:
        trusted_root_key_id = AuditAttestationKeyring.initialize_development_root_marker(
            root_key_id_path, key_id
        )
    elif created:
        trusted_root_key_id = key_id
    else:
        raise ValueError("AUDIT_ATTESTATION_TRUSTED_ROOT_KEY_ID is required for an existing key")
    key_id = AuditAttestationKeyring(keyring_path, trusted_root_key_id).initialize(
        public_path,
        expected_chain_id=chain_id,
    )
    LOGGER.info(
        "audit_attestation_key_ready",
        extra={
            "key_created": created,
            "key_id": key_id,
            "external_root_pin_required": not configured_root_key_id and not allow_colocated_root,
            "public_key_path": str(public_path),
        },
    )


if __name__ == "__main__":
    main()
