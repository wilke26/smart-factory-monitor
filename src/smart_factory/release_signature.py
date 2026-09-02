"""Create externally anchored Ed25519 signatures for verified release bundles."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ALGORITHM = "Ed25519"
SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(document: Any) -> bytes:
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _regular_file(path: Path, description: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} must be a regular file")
    return path


def _validate_destination(path: Path, description: str) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing {description}: {path.name}")
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError(f"{description} parent must be a real directory")


def _write_once(path: Path, content: bytes, mode: int) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary_path, path)
        temporary_path.unlink()
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return path


def signing_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(public_der).hexdigest()


def _load_public_key(path: Path) -> Ed25519PublicKey:
    _regular_file(path, "release-signing public key")
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("release-signing public key must be Ed25519")
    return key


def signing_key_fingerprint_from_path(path: Path) -> str:
    return signing_key_fingerprint(_load_public_key(path))


def _load_private_key(path: Path, password: bytes) -> Ed25519PrivateKey:
    _regular_file(path, "release-signing private key")
    if not password:
        raise ValueError("release-signing private key password must not be empty")
    key = serialization.load_pem_private_key(path.read_bytes(), password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("release-signing private key must be Ed25519")
    return key


def generate_signing_key_pair(
    private_key_path: Path,
    public_key_path: Path,
    password: bytes,
) -> tuple[Path, Path]:
    if private_key_path == public_key_path:
        raise ValueError("private and public key paths must differ")
    if not password:
        raise ValueError("release-signing private key password must not be empty")
    _validate_destination(private_key_path, "private key")
    _validate_destination(public_key_path, "public key")

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _write_once(private_key_path, private_pem, 0o600)
    try:
        _write_once(public_key_path, public_pem, 0o644)
    except BaseException:
        private_key_path.unlink(missing_ok=True)
        raise
    return private_key_path, public_key_path


def release_signature_name(version: str) -> str:
    return f"smart_factory_monitor-{version}.release-signature.json"


def _signature_payload(
    directory: Path,
    release: dict[str, Any],
    signing_key_sha256: str,
) -> dict[str, Any]:
    return {
        "algorithm": ALGORITHM,
        "schema_version": SCHEMA_VERSION,
        "signed_release": {
            "checksums": {"name": "SHA256SUMS", "sha256": _sha256(directory / "SHA256SUMS")},
            "container_reference": release["container"]["reference"],
            "manifest": {
                "name": "release-manifest.json",
                "sha256": _sha256(directory / "release-manifest.json"),
            },
            "name": "smart-factory-monitor",
            "revision": release["revision"],
            "version": release["version"],
        },
        "signing_key_sha256": signing_key_sha256,
    }


def sign_release_bundle(
    directory: Path,
    signature_path: Path,
    private_key_path: Path,
    password: bytes,
) -> Path:
    from smart_factory.release_verification import verify_release_bundle

    _validate_destination(signature_path, "release signature")
    release = verify_release_bundle(directory)
    expected_name = release_signature_name(release["version"])
    if signature_path.name != expected_name:
        raise ValueError(f"release signature must be named {expected_name}")
    private_key = _load_private_key(private_key_path, password)
    payload = _signature_payload(
        directory,
        release,
        signing_key_fingerprint(private_key.public_key()),
    )
    signature = private_key.sign(_canonical_json(payload))
    document = {**payload, "signature": base64.b64encode(signature).decode("ascii")}
    return _write_once(signature_path, _canonical_json(document) + b"\n", 0o644)


def verify_release_signature(
    directory: Path,
    signature_path: Path,
    public_key_path: Path,
    release: dict[str, Any],
) -> dict[str, str]:
    _regular_file(signature_path, "release signature")
    expected_name = release_signature_name(release["version"])
    if signature_path.name != expected_name:
        raise ValueError(f"release signature must be named {expected_name}")
    try:
        document: Any = json.loads(signature_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("release signature must be valid UTF-8 JSON") from error
    if not isinstance(document, dict) or set(document) != {
        "algorithm",
        "schema_version",
        "signature",
        "signed_release",
        "signing_key_sha256",
    }:
        raise ValueError("release signature document is invalid")

    public_key = _load_public_key(public_key_path)
    fingerprint = signing_key_fingerprint(public_key)
    payload = {name: value for name, value in document.items() if name != "signature"}
    if payload != _signature_payload(directory, release, fingerprint):
        raise ValueError("release signature is bound to different release evidence or key")
    encoded_signature = document.get("signature")
    if not isinstance(encoded_signature, str):
        raise ValueError("release signature encoding is invalid")
    try:
        signature = base64.b64decode(encoded_signature, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("release signature encoding is invalid") from error
    if len(signature) != 64:
        raise ValueError("release signature encoding is invalid")
    try:
        public_key.verify(signature, _canonical_json(payload))
    except InvalidSignature as error:
        raise ValueError("release signature authentication failed") from error
    return {"algorithm": ALGORITHM, "signing_key_sha256": fingerprint}


def _password_from_environment(name: str) -> bytes:
    password = os.getenv(name)
    if password is None:
        raise ValueError("release-signing key password environment variable is not set")
    if not password:
        raise ValueError("release-signing key password must not be empty")
    return password.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    key_parser = subparsers.add_parser("generate-key")
    key_parser.add_argument("--private-key", type=Path, required=True)
    key_parser.add_argument("--public-key", type=Path, required=True)
    key_parser.add_argument("--private-key-password-env", required=True)
    sign_parser = subparsers.add_parser("sign")
    sign_parser.add_argument("directory", type=Path)
    sign_parser.add_argument("--output", type=Path, required=True)
    sign_parser.add_argument("--private-key", type=Path, required=True)
    sign_parser.add_argument("--private-key-password-env", required=True)
    arguments = parser.parse_args()
    try:
        password = _password_from_environment(arguments.private_key_password_env)
        if arguments.command == "generate-key":
            generate_signing_key_pair(
                arguments.private_key,
                arguments.public_key,
                password,
            )
            print(f"Generated release-signing key: {arguments.public_key}")
            print(
                "Release-signing key SHA-256: "
                f"{signing_key_fingerprint_from_path(arguments.public_key)}"
            )
            return
        signature_path = sign_release_bundle(
            arguments.directory,
            arguments.output,
            arguments.private_key,
            password,
        )
        print(f"Created release signature: {signature_path}")
    except (OSError, TypeError, ValueError) as error:
        print(f"Release signature operation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
