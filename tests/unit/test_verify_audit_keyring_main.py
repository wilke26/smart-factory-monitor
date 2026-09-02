from pathlib import Path

from smart_factory.config import AuditKeyringSettings
from smart_factory.infrastructure.audit.checkpoint import public_key_id
from smart_factory.infrastructure.audit.keyring import AuditAttestationKeyring
from smart_factory.verify_audit_keyring_main import run


def test_reports_verified_keyring_without_private_key(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    _, public_path = model_signing_keys
    root_key_id = public_key_id(public_path)
    keyring_path = tmp_path / "keyring"
    AuditAttestationKeyring(keyring_path, root_key_id).initialize(public_path)

    result = run(
        AuditKeyringSettings(
            chain_id="factory-production",
            keyring_path=str(keyring_path),
            trusted_root_key_id=root_key_id,
        )
    )

    assert result.trusted_root_key_id == root_key_id
    assert result.active_key_id == root_key_id
    assert result.key_ids == (root_key_id,)
    assert result.transition_ids == ()
