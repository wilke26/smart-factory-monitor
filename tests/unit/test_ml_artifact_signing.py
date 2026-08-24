from pathlib import Path

import pytest

from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactSigningError,
    ArtifactVerifier,
    ensure_ed25519_key_pair,
)


def test_creates_and_reuses_matching_ed25519_key_pair(tmp_path: Path) -> None:
    private_path = tmp_path / "private" / "private.pem"
    public_path = tmp_path / "public" / "public.pem"

    assert ensure_ed25519_key_pair(private_path, public_path) is True
    original_private = private_path.read_bytes()
    original_public = public_path.read_bytes()

    assert ensure_ed25519_key_pair(private_path, public_path) is False
    assert private_path.read_bytes() == original_private
    assert public_path.read_bytes() == original_public
    assert private_path.stat().st_mode & 0o777 == 0o600
    assert public_path.stat().st_mode & 0o777 == 0o644


def test_signature_verifies_only_exact_payload(
    artifact_signer: ArtifactSigner,
    artifact_verifier: ArtifactVerifier,
) -> None:
    payload = b"verified model bytes"
    signature = artifact_signer.sign(payload)

    artifact_verifier.verify(payload, signature)

    with pytest.raises(ArtifactSigningError, match="signature is invalid"):
        artifact_verifier.verify(payload + b"tampered", signature)


def test_rejects_partial_key_pair(tmp_path: Path) -> None:
    private_path = tmp_path / "private.pem"
    private_path.touch()

    with pytest.raises(ArtifactSigningError, match="must exist together"):
        ensure_ed25519_key_pair(private_path, tmp_path / "public.pem")


def test_rejects_mismatched_key_pair(tmp_path: Path) -> None:
    first_private = tmp_path / "first-private.pem"
    first_public = tmp_path / "first-public.pem"
    second_private = tmp_path / "second-private.pem"
    second_public = tmp_path / "second-public.pem"
    ensure_ed25519_key_pair(first_private, first_public)
    ensure_ed25519_key_pair(second_private, second_public)
    first_public.write_bytes(second_public.read_bytes())

    with pytest.raises(ArtifactSigningError, match="signature is invalid"):
        ensure_ed25519_key_pair(first_private, first_public)
