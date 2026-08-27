from datetime import UTC, datetime
from pathlib import Path

import pytest

from smart_factory.domain.operator_audit import AuditChainVerification
from smart_factory.infrastructure.audit.checkpoint import (
    AuditCheckpointError,
    create_signed_checkpoint,
    load_signed_checkpoint,
    verify_signed_checkpoint,
    write_signed_checkpoint,
)
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactVerifier,
    ensure_ed25519_key_pair,
)


def verification() -> AuditChainVerification:
    return AuditChainVerification(valid=True, event_count=7, head_hash="a" * 64)


def test_round_trips_signed_checkpoint_without_database(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = model_signing_keys
    envelope = create_signed_checkpoint(
        verification(),
        chain_id="factory-production",
        signer=ArtifactSigner.from_private_key_file(private_path),
        public_key_path=public_path,
        created_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    )
    checkpoint_path = tmp_path / "checkpoint.json"

    write_signed_checkpoint(checkpoint_path, envelope)
    verified = verify_signed_checkpoint(
        load_signed_checkpoint(checkpoint_path),
        verifier=ArtifactVerifier.from_public_key_file(public_path),
        public_key_path=public_path,
        expected_chain_id="factory-production",
    )

    assert verified.event_count == 7
    assert verified.head_hash == "a" * 64
    assert verified.created_at == datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def test_rejects_tampered_checkpoint_and_unexpected_chain(
    model_signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = model_signing_keys
    envelope = create_signed_checkpoint(
        verification(),
        chain_id="factory-production",
        signer=ArtifactSigner.from_private_key_file(private_path),
        public_key_path=public_path,
    )
    tampered = envelope.model_copy(
        update={"checkpoint": envelope.checkpoint.model_copy(update={"event_count": 8})}
    )
    verifier = ArtifactVerifier.from_public_key_file(public_path)

    with pytest.raises(AuditCheckpointError, match="signature is invalid"):
        verify_signed_checkpoint(
            tampered,
            verifier=verifier,
            public_key_path=public_path,
            expected_chain_id="factory-production",
        )
    with pytest.raises(AuditCheckpointError, match="unexpected chain"):
        verify_signed_checkpoint(
            envelope,
            verifier=verifier,
            public_key_path=public_path,
            expected_chain_id="factory-staging",
        )


def test_rejects_wrong_key_and_invalid_source(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = model_signing_keys
    envelope = create_signed_checkpoint(
        verification(),
        chain_id="factory-production",
        signer=ArtifactSigner.from_private_key_file(private_path),
        public_key_path=public_path,
    )
    other_private = tmp_path / "other-private.pem"
    other_public = tmp_path / "other-public.pem"
    ensure_ed25519_key_pair(other_private, other_public)

    with pytest.raises(AuditCheckpointError, match="key identity"):
        verify_signed_checkpoint(
            envelope,
            verifier=ArtifactVerifier.from_public_key_file(other_public),
            public_key_path=other_public,
            expected_chain_id="factory-production",
        )
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not-json")
    with pytest.raises(AuditCheckpointError, match="could not load"):
        load_signed_checkpoint(invalid_path)


def test_refuses_to_replace_existing_checkpoint(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = model_signing_keys
    envelope = create_signed_checkpoint(
        verification(),
        chain_id="factory-production",
        signer=ArtifactSigner.from_private_key_file(private_path),
        public_key_path=public_path,
    )
    path = tmp_path / "checkpoint.json"
    write_signed_checkpoint(path, envelope)

    with pytest.raises(AuditCheckpointError, match="already exists"):
        write_signed_checkpoint(path, envelope)


def test_refuses_checkpoint_for_invalid_chain(model_signing_keys: tuple[Path, Path]) -> None:
    private_path, public_path = model_signing_keys
    with pytest.raises(AuditCheckpointError, match="invalid operator audit chain"):
        create_signed_checkpoint(
            AuditChainVerification(
                valid=False,
                event_count=2,
                head_hash="a" * 64,
                invalid_sequence_number=2,
            ),
            chain_id="factory-production",
            signer=ArtifactSigner.from_private_key_file(private_path),
            public_key_path=public_path,
        )


def test_rejects_mismatched_attestation_key_pair(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    private_path, _ = model_signing_keys
    other_private = tmp_path / "other-private.pem"
    other_public = tmp_path / "other-public.pem"
    ensure_ed25519_key_pair(other_private, other_public)

    with pytest.raises(AuditCheckpointError, match="key pair does not match"):
        create_signed_checkpoint(
            verification(),
            chain_id="factory-production",
            signer=ArtifactSigner.from_private_key_file(private_path),
            public_key_path=other_public,
        )
