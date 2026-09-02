"""Offline verification for a complete Smart Factory Monitor release bundle."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?(?::[0-9]+)?"
    r"(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)+$"
)
PLATFORM_PATTERN = re.compile(r"^linux/(?:amd64|arm64)$")
CHECKSUM_LINE_PATTERN = re.compile(r"^([0-9a-f]{64})  ([^/\\]+)$")
ENCRYPTION_ALGORITHM = "RSA-OAEP-SHA256+A256GCM"
EXPECTED_DEPLOYMENTS = 3


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain_name(value: object, description: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise ValueError(f"{description} name is invalid")
    return value


def _regular_file(path: Path, description: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} must be a regular file: {path.name}")
    return path


def _read_json(path: Path, description: str) -> dict[str, Any]:
    _regular_file(path, description)
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object")
    return value


def _validate_record(
    directory: Path,
    record: object,
    description: str,
    *,
    expected_name: str,
    expected_media_type: str | None = None,
) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{description} record is invalid")
    name = _plain_name(record.get("name"), description)
    digest = record.get("sha256")
    size = record.get("size")
    if name != expected_name:
        raise ValueError(f"{description} name does not match the release identity")
    if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        raise ValueError(f"{description} digest is invalid")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError(f"{description} size is invalid")
    if expected_media_type is not None and record.get("media_type") != expected_media_type:
        raise ValueError(f"{description} media type is invalid")
    path = _regular_file(directory / name, description)
    if path.stat().st_size != size or _sha256(path) != digest:
        raise ValueError(f"{description} does not match its recorded identity")
    return path


def _validate_base64(value: object, field: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError(f"encrypted SBOM field {field} is invalid")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError(f"encrypted SBOM field {field} is invalid") from error


def _validate_encrypted_sbom(
    directory: Path,
    metadata: object,
    *,
    version: str,
    revision: str,
    scope: str,
    plaintext_name: str,
    encrypted_name: str,
) -> tuple[Path, str]:
    if not isinstance(metadata, dict):
        raise ValueError(f"{scope} SBOM metadata is invalid")
    plaintext_digest = metadata.get("sha256")
    package_count = metadata.get("package_count")
    if (
        metadata.get("format") != "SPDX-2.x"
        or metadata.get("scope") != scope
        or _plain_name(metadata.get("name"), f"{scope} SBOM") != plaintext_name
        or not isinstance(plaintext_digest, str)
        or not SHA256_PATTERN.fullmatch(plaintext_digest)
        or not isinstance(package_count, int)
        or isinstance(package_count, bool)
        or package_count < 1
    ):
        raise ValueError(f"{scope} SBOM metadata is invalid")
    encrypted = metadata.get("encrypted")
    encrypted_path = _validate_record(
        directory,
        encrypted,
        f"encrypted {scope} SBOM",
        expected_name=encrypted_name,
    )
    if not isinstance(encrypted, dict) or encrypted.get("algorithm") != ENCRYPTION_ALGORITHM:
        raise ValueError(f"encrypted {scope} SBOM algorithm is invalid")
    recipient = encrypted.get("recipient_key_sha256")
    if not isinstance(recipient, str) or not SHA256_PATTERN.fullmatch(recipient):
        raise ValueError(f"encrypted {scope} SBOM recipient fingerprint is invalid")

    envelope = _read_json(encrypted_path, f"encrypted {scope} SBOM")
    identity = {"name": plaintext_name, "revision": revision, "version": version}
    if (
        envelope.get("schema_version") != 1
        or envelope.get("algorithm") != ENCRYPTION_ALGORITHM
        or envelope.get("authenticated_release") != identity
        or envelope.get("recipient_key_sha256") != recipient
    ):
        raise ValueError(f"encrypted {scope} SBOM identity is invalid")
    encrypted_key = _validate_base64(envelope.get("encrypted_key"), "encrypted_key")
    nonce = _validate_base64(envelope.get("nonce"), "nonce")
    ciphertext = _validate_base64(envelope.get("ciphertext"), "ciphertext")
    if not encrypted_key or len(nonce) != 12 or len(ciphertext) < 16:
        raise ValueError(f"encrypted {scope} SBOM cryptographic fields are invalid")
    return encrypted_path, recipient


def _parse_checksums(path: Path) -> dict[str, str]:
    _regular_file(path, "checksum file")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError("SHA256SUMS must be valid UTF-8 text") from error
    if not content or not content.endswith("\n"):
        raise ValueError("SHA256SUMS must be nonempty and newline-terminated")
    checksums: dict[str, str] = {}
    for line in content.splitlines():
        match = CHECKSUM_LINE_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError("SHA256SUMS contains an invalid line")
        digest, name = match.groups()
        _plain_name(name, "checksum entry")
        if name in checksums:
            raise ValueError(f"SHA256SUMS contains a duplicate entry: {name}")
        checksums[name] = digest
    return checksums


def _validate_sbom_plaintext(path: Path, metadata: dict[str, Any], scope: str) -> dict[str, Any]:
    if _sha256(path) != metadata["sha256"]:
        raise ValueError(f"recovered {scope} SBOM digest does not match the manifest")
    document = _read_json(path, f"recovered {scope} SBOM")
    if not str(document.get("spdxVersion", "")).startswith("SPDX-2."):
        raise ValueError(f"recovered {scope} SBOM is not an SPDX 2.x document")
    packages = document.get("packages")
    if not isinstance(packages, list) or len(packages) != metadata["package_count"]:
        raise ValueError(f"recovered {scope} SBOM package count does not match the manifest")
    return {"package_count": len(packages), "sha256": metadata["sha256"]}


def _recover_sboms(
    directory: Path,
    manifest: dict[str, Any],
    private_key_path: Path,
    password: bytes | None,
) -> dict[str, dict[str, Any]]:
    try:
        from smart_factory.release_evidence_crypto import decrypt_release_evidence
    except ImportError as error:
        raise ValueError(
            "private SBOM recovery requires the smart-factory-monitor ml extra"
        ) from error

    version = manifest["version"]
    revision = manifest["revision"]
    recovered: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="smart-factory-release-verify-") as temporary:
        temporary_path = Path(temporary)
        temporary_path.chmod(0o700)
        for label, metadata in (
            ("ml-runtime", manifest["sbom"]),
            ("container-image", manifest["container"]["sbom"]),
        ):
            output = temporary_path / metadata["name"]
            decrypt_release_evidence(
                directory / metadata["encrypted"]["name"],
                output,
                private_key_path,
                version,
                revision,
                password=password,
            )
            recovered[label] = _validate_sbom_plaintext(output, metadata, label)
    return recovered


def verify_release_bundle(
    directory: Path,
    *,
    expected_version: str | None = None,
    expected_revision: str | None = None,
    expected_image_reference: str | None = None,
    public_key_path: Path | None = None,
    private_key_path: Path | None = None,
    private_key_password: bytes | None = None,
) -> dict[str, Any]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("release bundle must be a real directory")
    for path in directory.iterdir():
        _regular_file(path, "release bundle entry")

    manifest = _read_json(directory / "release-manifest.json", "release manifest")
    if manifest.get("schema_version") != 3 or manifest.get("name") != "smart-factory-monitor":
        raise ValueError("release manifest schema or product identity is invalid")
    version = manifest.get("version")
    revision = manifest.get("revision")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ValueError("release version is invalid")
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise ValueError("release revision is invalid")
    if expected_version is not None and version != expected_version:
        raise ValueError("release version does not match the expected version")
    if expected_revision is not None and revision != expected_revision:
        raise ValueError("release revision does not match the expected revision")

    stem = f"smart_factory_monitor-{version}"
    wheel_name = f"{stem}-py3-none-any.whl"
    source_name = f"{stem}.tar.gz"
    ml_plaintext_name = f"{stem}.ml-runtime.spdx.json"
    ml_encrypted_name = f"{ml_plaintext_name}.enc"
    container_plaintext_name = f"{stem}.container.spdx.json"
    container_encrypted_name = f"{container_plaintext_name}.enc"
    deployment_name = f"{stem}.kubernetes.yaml"

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise ValueError("release manifest must contain exactly two package artifacts")
    records = {
        _plain_name(record.get("name"), "package artifact"): record
        for record in artifacts
        if isinstance(record, dict)
    }
    if len(records) != 2 or set(records) != {wheel_name, source_name}:
        raise ValueError("release package artifact names are invalid")
    _validate_record(
        directory,
        records[wheel_name],
        "wheel artifact",
        expected_name=wheel_name,
        expected_media_type="application/zip",
    )
    _validate_record(
        directory,
        records[source_name],
        "source artifact",
        expected_name=source_name,
        expected_media_type="application/gzip",
    )

    ml_metadata = manifest.get("sbom")
    _, ml_recipient = _validate_encrypted_sbom(
        directory,
        ml_metadata,
        version=version,
        revision=revision,
        scope="ml-runtime",
        plaintext_name=ml_plaintext_name,
        encrypted_name=ml_encrypted_name,
    )
    container = manifest.get("container")
    if not isinstance(container, dict):
        raise ValueError("container metadata is invalid")
    image = container.get("image")
    digest = container.get("digest")
    reference = container.get("reference")
    platform = container.get("platform")
    if (
        not isinstance(image, str)
        or not IMAGE_PATTERN.fullmatch(image)
        or not isinstance(digest, str)
        or not DIGEST_PATTERN.fullmatch(digest)
        or reference != f"{image}@{digest}"
        or not isinstance(platform, str)
        or not PLATFORM_PATTERN.fullmatch(platform)
    ):
        raise ValueError("container identity is invalid")
    if expected_image_reference is not None and reference != expected_image_reference:
        raise ValueError("container reference does not match the expected image")
    container_metadata = container.get("sbom")
    _, container_recipient = _validate_encrypted_sbom(
        directory,
        container_metadata,
        version=version,
        revision=revision,
        scope="container-image",
        plaintext_name=container_plaintext_name,
        encrypted_name=container_encrypted_name,
    )
    if ml_recipient != container_recipient:
        raise ValueError("release SBOMs use different recipient keys")

    deployment = container.get("deployment_manifest")
    deployment_path = _validate_record(
        directory,
        deployment,
        "deployment manifest",
        expected_name=deployment_name,
        expected_media_type="application/yaml",
    )
    try:
        deployment_text = deployment_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("deployment manifest must be UTF-8 YAML") from error
    documents = re.split(r"(?m)^---\s*$", deployment_text)
    deployment_documents = [
        document for document in documents if re.search(r"(?m)^kind: Deployment\s*$", document)
    ]
    deployment_images = [
        re.findall(r"(?m)^\s+(?:-\s+)?image:\s+(\S+)\s*$", document)
        for document in deployment_documents
    ]
    if len(deployment_documents) != EXPECTED_DEPLOYMENTS or any(
        images != [reference] for images in deployment_images
    ):
        raise ValueError("deployment manifest is not fully bound to the release container")

    expected_files = {
        "SHA256SUMS",
        "release-manifest.json",
        wheel_name,
        source_name,
        ml_encrypted_name,
        container_encrypted_name,
        deployment_name,
    }
    actual_files = {path.name for path in directory.iterdir()}
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        raise ValueError(
            f"release bundle membership is invalid: missing={missing}, unexpected={unexpected}"
        )
    checksums = _parse_checksums(directory / "SHA256SUMS")
    expected_checksum_names = expected_files - {"SHA256SUMS"}
    if set(checksums) != expected_checksum_names:
        raise ValueError("SHA256SUMS membership does not match the release bundle")
    for name, expected_digest in checksums.items():
        if _sha256(directory / name) != expected_digest:
            raise ValueError(f"checksum mismatch: {name}")

    if public_key_path is not None:
        try:
            from smart_factory.release_evidence_crypto import public_key_fingerprint_from_path
        except ImportError as error:
            raise ValueError(
                "public-key verification requires the smart-factory-monitor ml extra"
            ) from error
        if public_key_fingerprint_from_path(public_key_path) != ml_recipient:
            raise ValueError("public key does not match the release recipient fingerprint")

    recovered: dict[str, dict[str, Any]] | None = None
    if private_key_path is not None:
        recovered = _recover_sboms(
            directory,
            manifest,
            private_key_path,
            private_key_password,
        )

    result: dict[str, Any] = {
        "container": {"platform": platform, "reference": reference},
        "files_checked": len(expected_checksum_names),
        "recipient_key_sha256": ml_recipient,
        "revision": revision,
        "status": "verified",
        "version": version,
    }
    if public_key_path is not None:
        result["public_key_verified"] = True
    if recovered is not None:
        result["recovered_sboms"] = recovered
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-revision")
    parser.add_argument("--expected-image-reference")
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--private-key-password-env")
    parser.add_argument("--json", action="store_true", dest="json_output")
    arguments = parser.parse_args()
    try:
        if arguments.private_key_password_env and arguments.private_key is None:
            raise ValueError("--private-key-password-env requires --private-key")
        password = None
        if arguments.private_key_password_env:
            raw_password = os.getenv(arguments.private_key_password_env)
            if raw_password is None:
                raise ValueError("private key password environment variable is not set")
            password = raw_password.encode("utf-8")
        result = verify_release_bundle(
            arguments.directory,
            expected_version=arguments.expected_version,
            expected_revision=arguments.expected_revision,
            expected_image_reference=arguments.expected_image_reference,
            public_key_path=arguments.public_key,
            private_key_path=arguments.private_key,
            private_key_password=password,
        )
    except (OSError, TypeError, ValueError) as error:
        if arguments.json_output:
            print(json.dumps({"error": str(error), "status": "invalid"}, sort_keys=True))
        else:
            print(f"Release bundle verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    if arguments.json_output:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"Verified Smart Factory Monitor release {result['version']}")
        print(f"Revision: {result['revision']}")
        print(f"Container: {result['container']['reference']}")
        print(f"Checksummed files: {result['files_checked']}")
        if result.get("public_key_verified"):
            print("Recipient public key: verified")
        if "recovered_sboms" in result:
            print("Private SBOMs: authenticated, recovered, and verified")


if __name__ == "__main__":
    main()
