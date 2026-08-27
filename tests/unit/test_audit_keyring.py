import json
from pathlib import Path

import pytest

from smart_factory.domain.operator_audit import AuditChainVerification
from smart_factory.infrastructure.audit.checkpoint import (
    AuditCheckpointError,
    create_signed_checkpoint,
    public_key_id,
    verify_signed_checkpoint,
)
from smart_factory.infrastructure.audit.keyring import (
    AuditAttestationKeyring,
    FilesystemAuditAttestationKeyRotator,
)
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactVerifier,
    ensure_ed25519_key_pair,
)


def initialized_keyring(tmp_path: Path) -> tuple[AuditAttestationKeyring, Path, Path, str]:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    ensure_ed25519_key_pair(private_path, public_path)
    keyring = AuditAttestationKeyring(
        tmp_path / "keyring",
        tmp_path / "trusted-root-key-id",
    )
    root_id = keyring.initialize(public_path)
    return keyring, private_path, public_path, root_id


def test_initial_key_is_trusted_root_and_reinitialization_is_idempotent(tmp_path: Path) -> None:
    keyring, _, public_path, root_id = initialized_keyring(tmp_path)

    assert keyring.initialize(public_path) == root_id
    assert keyring.active_key_id() == root_id
    assert keyring.resolve_trusted_key(root_id, expected_chain_id="factory-production") == (
        tmp_path / "keyring" / "keys" / f"{root_id}.pem"
    )


def test_rotates_with_dual_signature_and_keeps_both_keys_trusted(tmp_path: Path) -> None:
    keyring, private_path, public_path, root_id = initialized_keyring(tmp_path)
    rotator = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    )

    result = rotator.rotate()

    assert result.previous_key_id == root_id
    assert result.new_key_id == public_key_id(public_path)
    assert keyring.active_key_id() == result.new_key_id
    assert keyring.resolve_trusted_key(root_id, expected_chain_id="factory-production").is_file()
    assert keyring.resolve_trusted_key(
        result.new_key_id, expected_chain_id="factory-production"
    ).is_file()
    assert list(private_path.parent.glob(".pending-*.pem")) == []


def test_checkpoints_before_and_after_rotation_share_one_trust_anchor(tmp_path: Path) -> None:
    keyring, private_path, public_path, _ = initialized_keyring(tmp_path)
    verification = AuditChainVerification(valid=True, event_count=3, head_hash="a" * 64)
    before = create_signed_checkpoint(
        verification,
        chain_id="factory-production",
        signer=ArtifactSigner.from_private_key_file(private_path),
        public_key_path=public_path,
    )
    FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    ).rotate()
    after = create_signed_checkpoint(
        verification,
        chain_id="factory-production",
        signer=ArtifactSigner.from_private_key_file(private_path),
        public_key_path=public_path,
    )

    for envelope in (before, after):
        trusted_key = keyring.resolve_trusted_key(
            envelope.checkpoint.key_id,
            expected_chain_id="factory-production",
        )
        verified = verify_signed_checkpoint(
            envelope,
            verifier=ArtifactVerifier.from_public_key_file(trusted_key),
            public_key_path=trusted_key,
            expected_chain_id="factory-production",
        )
        assert verified.key_id == envelope.checkpoint.key_id


def test_rejects_tampered_transition_and_wrong_chain(tmp_path: Path) -> None:
    keyring, private_path, public_path, _ = initialized_keyring(tmp_path)
    result = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    ).rotate()
    transition_path = next((tmp_path / "keyring" / "transitions").glob("*.json"))
    document = json.loads(transition_path.read_text())
    document["previous_signature"] = document["new_signature"]
    transition_path.write_text(json.dumps(document))

    with pytest.raises(AuditCheckpointError, match="signature is invalid"):
        keyring.resolve_trusted_key(result.new_key_id, expected_chain_id="factory-production")
    with pytest.raises(AuditCheckpointError, match="unexpected chain"):
        keyring.resolve_trusted_key(result.new_key_id, expected_chain_id="factory-staging")


def test_rejects_untrusted_root_replacement(tmp_path: Path) -> None:
    keyring, _, _, root_id = initialized_keyring(tmp_path)
    other_private = tmp_path / "other-private.pem"
    other_public = tmp_path / "other-public.pem"
    ensure_ed25519_key_pair(other_private, other_public)
    keyring.key_path(root_id).write_bytes(other_public.read_bytes())

    with pytest.raises(AuditCheckpointError, match="identity is invalid"):
        keyring.resolve_trusted_key(root_id, expected_chain_id="factory-production")
