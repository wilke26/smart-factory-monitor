import json
from pathlib import Path
from threading import Barrier, Event, Thread

import pytest

from smart_factory.domain.audit_keyring import AuditKeyRotationResult
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
    root_id = public_key_id(public_path)
    keyring = AuditAttestationKeyring(
        tmp_path / "keyring",
        root_id,
    )
    keyring.initialize(public_path)
    return keyring, private_path, public_path, root_id


def rotate(rotator: FilesystemAuditAttestationKeyRotator) -> AuditKeyRotationResult:
    with rotator.exclusive():
        return rotator.rotate()


def test_initial_key_is_trusted_root_and_reinitialization_is_idempotent(tmp_path: Path) -> None:
    keyring, _, public_path, root_id = initialized_keyring(tmp_path)

    assert keyring.initialize(public_path) == root_id
    assert keyring.active_key_id() == root_id
    assert keyring.resolve_trusted_key(root_id, expected_chain_id="factory-production") == (
        tmp_path / "keyring" / "keys" / f"{root_id}.pem"
    )


def test_development_root_marker_remains_pinned_after_active_key_changes(
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "trusted-root-key-id"
    root_id = "a" * 64
    replacement_id = "b" * 64

    assert (
        AuditAttestationKeyring.initialize_development_root_marker(marker_path, root_id) == root_id
    )
    assert (
        AuditAttestationKeyring.initialize_development_root_marker(marker_path, replacement_id)
        == root_id
    )
    assert marker_path.read_text() == f"{root_id}\n"


def test_rotates_with_dual_signature_and_keeps_both_keys_trusted(tmp_path: Path) -> None:
    keyring, private_path, public_path, root_id = initialized_keyring(tmp_path)
    rotator = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    )

    result = rotate(rotator)

    assert result.previous_key_id == root_id
    assert result.new_key_id == public_key_id(public_path)
    assert keyring.active_key_id() == result.new_key_id
    assert keyring.resolve_trusted_key(root_id, expected_chain_id="factory-production").is_file()
    assert keyring.resolve_trusted_key(
        result.new_key_id, expected_chain_id="factory-production"
    ).is_file()
    assert list(private_path.parent.glob(".pending-*.pem")) == []


def test_reinitializes_rotated_key_only_through_pinned_root_chain(tmp_path: Path) -> None:
    keyring, private_path, public_path, root_id = initialized_keyring(tmp_path)
    rotate(
        FilesystemAuditAttestationKeyRotator(
            chain_id="factory-production",
            private_key_path=private_path,
            public_key_path=public_path,
            keyring=keyring,
        )
    )

    restarted_keyring = AuditAttestationKeyring(tmp_path / "keyring", root_id)
    current_id = restarted_keyring.initialize(
        public_path,
        expected_chain_id="factory-production",
    )

    assert current_id == public_key_id(public_path)
    assert restarted_keyring.active_key_id() == current_id


def test_rejects_rotated_key_reinitialization_without_chain_identity(tmp_path: Path) -> None:
    keyring, private_path, public_path, root_id = initialized_keyring(tmp_path)
    rotate(
        FilesystemAuditAttestationKeyRotator(
            chain_id="factory-production",
            private_key_path=private_path,
            public_key_path=public_path,
            keyring=keyring,
        )
    )

    with pytest.raises(AuditCheckpointError, match="chain ID is required"):
        AuditAttestationKeyring(tmp_path / "keyring", root_id).initialize(public_path)


def test_checkpoints_before_and_after_rotation_share_one_trust_anchor(tmp_path: Path) -> None:
    keyring, private_path, public_path, _ = initialized_keyring(tmp_path)
    verification = AuditChainVerification(valid=True, event_count=3, head_hash="a" * 64)
    before = create_signed_checkpoint(
        verification,
        chain_id="factory-production",
        signer=ArtifactSigner.from_private_key_file(private_path),
        public_key_path=public_path,
    )
    rotator = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    )
    rotate(rotator)
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
    rotator = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    )
    result = rotate(rotator)
    transition_path = next((tmp_path / "keyring" / "transitions").glob("*.json"))
    document = json.loads(transition_path.read_text())
    document["previous_signature"] = document["new_signature"]
    transition_path.write_text(json.dumps(document))

    with pytest.raises(AuditCheckpointError, match="signature is invalid"):
        keyring.resolve_trusted_key(result.new_key_id, expected_chain_id="factory-production")
    with pytest.raises(AuditCheckpointError, match="unexpected chain"):
        keyring.resolve_trusted_key(result.new_key_id, expected_chain_id="factory-staging")


def test_refuses_rotation_when_active_key_is_no_longer_rooted(tmp_path: Path) -> None:
    keyring, private_path, public_path, _ = initialized_keyring(tmp_path)
    rotator = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    )
    rotate(rotator)
    transition_path = next((tmp_path / "keyring" / "transitions").glob("*.json"))
    transition_path.unlink()

    with pytest.raises(AuditCheckpointError, match="not trusted by the configured root"):
        rotator.current_key_id()

    assert list((tmp_path / "keyring" / "transitions").glob("*.json")) == []
    assert list(private_path.parent.glob(".pending-*.pem")) == []


def test_exclusive_rotation_serializes_independent_rotators(tmp_path: Path) -> None:
    keyring, private_path, public_path, _ = initialized_keyring(tmp_path)
    first = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    )
    second = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=AuditAttestationKeyring(
            tmp_path / "keyring",
            keyring.trusted_root_key_id(),
        ),
    )
    attempted = Event()
    entered = Event()

    def enter_second_rotation() -> None:
        attempted.set()
        with second.exclusive():
            entered.set()

    contender = Thread(target=enter_second_rotation)
    with first.exclusive():
        contender.start()
        assert attempted.wait(timeout=1)
        assert not entered.wait(timeout=0.1)

    assert entered.wait(timeout=1)
    contender.join(timeout=1)
    assert not contender.is_alive()


def test_rotation_requires_exclusive_context(tmp_path: Path) -> None:
    keyring, private_path, public_path, _ = initialized_keyring(tmp_path)
    rotator = FilesystemAuditAttestationKeyRotator(
        chain_id="factory-production",
        private_key_path=private_path,
        public_key_path=public_path,
        keyring=keyring,
    )

    with pytest.raises(AuditCheckpointError, match="requires exclusive lock"):
        rotator.rotate()


def test_concurrent_rotations_form_one_linear_trust_chain(tmp_path: Path) -> None:
    keyring, private_path, public_path, root_id = initialized_keyring(tmp_path)
    rotators = [
        FilesystemAuditAttestationKeyRotator(
            chain_id="factory-production",
            private_key_path=private_path,
            public_key_path=public_path,
            keyring=AuditAttestationKeyring(
                tmp_path / "keyring",
                root_id,
            ),
        )
        for _ in range(2)
    ]
    ready = Barrier(2)
    results: list[AuditKeyRotationResult] = []

    def rotate_concurrently(rotator: FilesystemAuditAttestationKeyRotator) -> None:
        ready.wait(timeout=1)
        results.append(rotate(rotator))

    contenders = [Thread(target=rotate_concurrently, args=(rotator,)) for rotator in rotators]
    for contender in contenders:
        contender.start()
    for contender in contenders:
        contender.join(timeout=2)
        assert not contender.is_alive()

    assert len(results) == 2
    assert {result.previous_key_id for result in results} == {
        root_id,
        next(result.new_key_id for result in results if result.previous_key_id == root_id),
    }
    active = keyring.active_key_id()
    assert keyring.resolve_trusted_key(active, expected_chain_id="factory-production").is_file()
    assert len(list((tmp_path / "keyring" / "transitions").glob("*.json"))) == 2


def test_rejects_untrusted_root_replacement(tmp_path: Path) -> None:
    keyring, _, _, root_id = initialized_keyring(tmp_path)
    other_private = tmp_path / "other-private.pem"
    other_public = tmp_path / "other-public.pem"
    ensure_ed25519_key_pair(other_private, other_public)
    keyring.key_path(root_id).write_bytes(other_public.read_bytes())

    with pytest.raises(AuditCheckpointError, match="identity is invalid"):
        keyring.resolve_trusted_key(root_id, expected_chain_id="factory-production")


def test_rejects_keyring_replacement_when_root_is_pinned_externally(tmp_path: Path) -> None:
    _, _, _, trusted_root_id = initialized_keyring(tmp_path / "trusted")
    replacement_private = tmp_path / "replacement-private.pem"
    replacement_public = tmp_path / "replacement-public.pem"
    ensure_ed25519_key_pair(replacement_private, replacement_public)
    replacement_root_id = public_key_id(replacement_public)
    replacement_keyring = AuditAttestationKeyring(
        tmp_path / "replacement-keyring", replacement_root_id
    )
    replacement_keyring.initialize(replacement_public)

    externally_pinned = AuditAttestationKeyring(tmp_path / "replacement-keyring", trusted_root_id)

    with pytest.raises(AuditCheckpointError, match="could not load audit attestation public key"):
        externally_pinned.resolve_trusted_key(
            replacement_root_id, expected_chain_id="factory-production"
        )
