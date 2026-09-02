"""Verify the complete audit-attestation trust chain without private-key access."""

import argparse
from pathlib import Path

from smart_factory.config import AuditKeyringSettings
from smart_factory.domain.audit_keyring import AuditKeyringVerification
from smart_factory.infrastructure.audit.keyring import AuditAttestationKeyring


def run(settings: AuditKeyringSettings) -> AuditKeyringVerification:
    return AuditAttestationKeyring(
        Path(settings.keyring_path),
        settings.resolve_trusted_root_key_id(),
    ).verify_integrity(expected_chain_id=settings.chain_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    verification = run(AuditKeyringSettings.from_env())
    if args.json:
        print(verification.model_dump_json())
        return
    print(f"Trusted root: {verification.trusted_root_key_id}")
    print(f"Active key: {verification.active_key_id}")
    print(f"Transitions: {len(verification.transition_ids)}")
    print(f"Snapshot SHA-256: {verification.snapshot_sha256}")


if __name__ == "__main__":
    main()
