#!/usr/bin/env python3
"""Encrypt or recover a private release SBOM with an external RSA trust anchor."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALGORITHM = "RSA-OAEP-SHA256+A256GCM"
SCHEMA_VERSION = 1


def _regular_file(path: Path, *, description: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} must be a regular file")
    return path


def _release_identity(version: str, revision: str, name: str) -> dict[str, str]:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must use numeric major.minor.patch format")
    if not REVISION_PATTERN.fullmatch(revision):
        raise ValueError("revision must be a full lowercase Git commit SHA")
    if not name or Path(name).name != name:
        raise ValueError("evidence name must be a plain filename")
    return {"name": name, "revision": revision, "version": version}


def _canonical_json(document: Any) -> bytes:
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _public_key_fingerprint(public_key: rsa.RSAPublicKey) -> str:
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(public_der).hexdigest()


def _decoded(value: object, *, field: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"encrypted evidence field {field} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError(f"encrypted evidence field {field} is invalid") from error


def _write_once(path: Path, content: bytes, mode: int) -> Path:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing output: {path.name}")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError("output parent must be a real directory")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return path


def encrypt_release_evidence(
    source: Path,
    destination: Path,
    public_key_path: Path,
    version: str,
    revision: str,
) -> Path:
    _regular_file(source, description="SBOM")
    _regular_file(public_key_path, description="recipient public key")
    identity = _release_identity(version, revision, source.name)
    public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 3072:
        raise ValueError("recipient public key must be RSA with at least 3072 bits")

    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    authenticated_identity = _canonical_json(identity)
    ciphertext = AESGCM(data_key).encrypt(nonce, source.read_bytes(), authenticated_identity)
    encrypted_key = public_key.encrypt(
        data_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    envelope = {
        "algorithm": ALGORITHM,
        "authenticated_release": identity,
        "ciphertext": _encoded(ciphertext),
        "encrypted_key": _encoded(encrypted_key),
        "nonce": _encoded(nonce),
        "recipient_key_sha256": _public_key_fingerprint(public_key),
        "schema_version": SCHEMA_VERSION,
    }
    return _write_once(destination, _canonical_json(envelope) + b"\n", 0o644)


def decrypt_release_evidence(
    source: Path,
    destination: Path,
    private_key_path: Path,
    version: str,
    revision: str,
    *,
    password: bytes | None = None,
) -> Path:
    _regular_file(source, description="encrypted release evidence")
    _regular_file(private_key_path, description="recipient private key")
    try:
        envelope: Any = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("encrypted release evidence must be valid UTF-8 JSON") from error
    if not isinstance(envelope, dict):
        raise ValueError("encrypted release evidence must be a JSON object")
    if envelope.get("schema_version") != SCHEMA_VERSION or envelope.get("algorithm") != ALGORITHM:
        raise ValueError("unsupported encrypted release evidence format")
    identity = envelope.get("authenticated_release")
    if not isinstance(identity, dict) or not isinstance(identity.get("name"), str):
        raise ValueError("encrypted release evidence identity is invalid")
    expected_identity = _release_identity(version, revision, identity["name"])
    if identity != expected_identity:
        raise ValueError("encrypted release evidence belongs to a different release")

    private_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(), password=password
    )
    if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 3072:
        raise ValueError("recipient private key must be RSA with at least 3072 bits")
    if envelope.get("recipient_key_sha256") != _public_key_fingerprint(private_key.public_key()):
        raise ValueError("encrypted release evidence targets a different recipient key")
    encrypted_key = _decoded(envelope.get("encrypted_key"), field="encrypted_key")
    nonce = _decoded(envelope.get("nonce"), field="nonce")
    ciphertext = _decoded(envelope.get("ciphertext"), field="ciphertext")
    if len(nonce) != 12:
        raise ValueError("encrypted release evidence nonce is invalid")
    try:
        data_key = private_key.decrypt(
            encrypted_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        plaintext = AESGCM(data_key).decrypt(nonce, ciphertext, _canonical_json(expected_identity))
    except (ValueError, InvalidTag) as error:
        raise ValueError("encrypted release evidence authentication failed") from error
    return _write_once(destination, plaintext, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    encrypt_parser = subparsers.add_parser("encrypt")
    encrypt_parser.add_argument("--input", type=Path, required=True)
    encrypt_parser.add_argument("--output", type=Path, required=True)
    encrypt_parser.add_argument("--public-key", type=Path, required=True)
    encrypt_parser.add_argument("--version", required=True)
    encrypt_parser.add_argument("--revision", required=True)

    decrypt_parser = subparsers.add_parser("decrypt")
    decrypt_parser.add_argument("--input", type=Path, required=True)
    decrypt_parser.add_argument("--output", type=Path, required=True)
    decrypt_parser.add_argument("--private-key", type=Path, required=True)
    decrypt_parser.add_argument("--version", required=True)
    decrypt_parser.add_argument("--revision", required=True)
    decrypt_parser.add_argument("--private-key-password-env")

    arguments = parser.parse_args()
    if arguments.command == "encrypt":
        encrypt_release_evidence(
            arguments.input,
            arguments.output,
            arguments.public_key,
            arguments.version,
            arguments.revision,
        )
        return

    password = None
    if arguments.private_key_password_env:
        raw_password = os.getenv(arguments.private_key_password_env)
        if raw_password is None:
            raise ValueError("private key password environment variable is not set")
        password = raw_password.encode("utf-8")
    decrypt_release_evidence(
        arguments.input,
        arguments.output,
        arguments.private_key,
        arguments.version,
        arguments.revision,
        password=password,
    )


if __name__ == "__main__":
    main()
