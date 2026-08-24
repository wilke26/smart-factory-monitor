"""Ed25519 signing boundary for model artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SIGNATURE_SUFFIX = ".sig"


class ArtifactSigningError(ValueError):
    """A signing key, signature, or key pair is invalid."""


def artifact_signature_path(artifact_path: Path) -> Path:
    """Return the detached-signature path for one model artifact."""
    return artifact_path.with_name(f"{artifact_path.name}{SIGNATURE_SUFFIX}")


class ArtifactSigner:
    """Sign immutable artifact bytes with a deployment-owned private key."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key

    @classmethod
    def from_private_key_file(cls, path: Path) -> ArtifactSigner:
        try:
            loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
        except (OSError, TypeError, ValueError, UnsupportedAlgorithm) as error:
            raise ArtifactSigningError(
                f"could not load Ed25519 private key {path}: {error}"
            ) from error
        if not isinstance(loaded, Ed25519PrivateKey):
            raise ArtifactSigningError(f"private key {path} is not an Ed25519 key")
        return cls(loaded)

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


class ArtifactVerifier:
    """Verify artifact bytes before any unsafe deserialization occurs."""

    def __init__(self, public_key: Ed25519PublicKey) -> None:
        self._public_key = public_key

    @classmethod
    def from_public_key_file(cls, path: Path) -> ArtifactVerifier:
        try:
            loaded = serialization.load_pem_public_key(path.read_bytes())
        except (OSError, ValueError, UnsupportedAlgorithm) as error:
            raise ArtifactSigningError(
                f"could not load Ed25519 public key {path}: {error}"
            ) from error
        if not isinstance(loaded, Ed25519PublicKey):
            raise ArtifactSigningError(f"public key {path} is not an Ed25519 key")
        return cls(loaded)

    def verify(self, payload: bytes, signature: bytes) -> None:
        try:
            self._public_key.verify(signature, payload)
        except InvalidSignature as error:
            raise ArtifactSigningError("model artifact signature is invalid") from error


def ensure_ed25519_key_pair(private_path: Path, public_path: Path) -> bool:
    """Create a key pair once or validate that the existing pair still matches."""
    private_exists = private_path.exists()
    public_exists = public_path.exists()
    if private_exists != public_exists:
        raise ArtifactSigningError("private and public model-signing keys must exist together")
    if private_exists:
        signer = ArtifactSigner.from_private_key_file(private_path)
        verifier = ArtifactVerifier.from_public_key_file(public_path)
        probe = b"smart-factory-model-signing-key-check"
        verifier.verify(probe, signer.sign(probe))
        return False

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _write_atomically(private_path, private_bytes, mode=0o600)
    _write_atomically(public_path, public_bytes, mode=0o644)
    return True


def _write_atomically(path: Path, payload: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as file:
        temporary_path = Path(file.name)
        file.write(payload)
    try:
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
