from pathlib import Path

from smart_factory.config import AuditCheckpointSettings
from smart_factory.domain.operator_audit import AuditChainVerification
from smart_factory.infrastructure.audit.checkpoint import (
    create_signed_checkpoint,
    public_key_id,
    write_signed_checkpoint,
)
from smart_factory.infrastructure.audit.keyring import AuditAttestationKeyring
from smart_factory.infrastructure.ml.artifact_signing import ArtifactSigner
from smart_factory.verify_audit_checkpoint_main import run


def test_verifies_checkpoint_without_database(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = model_signing_keys
    checkpoint_path = tmp_path / "checkpoint.json"
    keyring_path = tmp_path / "keyring"
    root_key_id = public_key_id(public_path)

    AuditAttestationKeyring(keyring_path, root_key_id).initialize(public_path)
    write_signed_checkpoint(
        checkpoint_path,
        create_signed_checkpoint(
            AuditChainVerification(valid=True, event_count=2, head_hash="a" * 64),
            chain_id="factory-production",
            signer=ArtifactSigner.from_private_key_file(private_path),
            public_key_path=public_path,
        ),
    )

    run(
        AuditCheckpointSettings(
            chain_id="factory-production",
            checkpoint_path=str(checkpoint_path),
            public_key_path=str(public_path),
            keyring_path=str(keyring_path),
            trusted_root_key_id=root_key_id,
        )
    )
