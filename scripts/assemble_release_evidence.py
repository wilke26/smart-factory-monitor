#!/usr/bin/env python3
"""Assemble package and container inputs into one digest-bound release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?(?::[0-9]+)?"
    r"(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)+$"
)
PLATFORM_PATTERN = re.compile(r"^linux/(?:amd64|arm64)$")
DEPLOYMENT_COUNT = 3


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"release input must be a regular file: {path.name}")
    return path


def _read_object(path: Path, description: str) -> dict[str, Any]:
    _regular_file(path)
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object")
    return value


def _validate_record(directory: Path, record: Any, description: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{description} record is invalid")
    name = record.get("name")
    digest = record.get("sha256")
    size = record.get("size")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError(f"{description} name is invalid")
    if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        raise ValueError(f"{description} digest is invalid")
    if not isinstance(size, int) or size < 0:
        raise ValueError(f"{description} size is invalid")
    path = _regular_file(directory / name)
    if path.stat().st_size != size or _sha256(path) != digest:
        raise ValueError(f"{description} does not match its recorded identity")
    return path


def _validate_sbom_metadata(
    path: Path,
    metadata: dict[str, Any],
    *,
    version: str,
    revision: str,
    scope: str,
) -> str:
    name = metadata.get("name")
    plaintext_digest = metadata.get("sha256")
    package_count = metadata.get("package_count")
    if (
        metadata.get("format") != "SPDX-2.x"
        or metadata.get("scope") != scope
        or not isinstance(name, str)
        or Path(name).name != name
        or not isinstance(plaintext_digest, str)
        or not SHA256_PATTERN.fullmatch(plaintext_digest)
        or not isinstance(package_count, int)
        or package_count < 1
    ):
        raise ValueError(f"{scope} SBOM metadata is invalid")
    envelope = _read_object(path, f"encrypted {scope} SBOM")
    recipient = envelope.get("recipient_key_sha256")
    if (
        envelope.get("schema_version") != 1
        or envelope.get("algorithm") != "RSA-OAEP-SHA256+A256GCM"
        or envelope.get("authenticated_release")
        != {"name": name, "revision": revision, "version": version}
        or not isinstance(recipient, str)
        or not SHA256_PATTERN.fullmatch(recipient)
    ):
        raise ValueError(f"encrypted {scope} SBOM identity is invalid")
    for field in ("ciphertext", "encrypted_key", "nonce"):
        if not isinstance(envelope.get(field), str) or not envelope[field]:
            raise ValueError(f"encrypted {scope} SBOM field {field} is invalid")
    return recipient


def _copy_unique(source: Path, output: Path, copied_names: set[str]) -> Path:
    if source.name in copied_names:
        raise ValueError(f"duplicate release artifact name: {source.name}")
    copied_names.add(source.name)
    destination = output / source.name
    shutil.copyfile(source, destination)
    return destination


def assemble_release_evidence(
    source_directory: Path,
    container_directory: Path,
    output_directory: Path,
    deployment_manifest: Path,
) -> tuple[Path, Path]:
    if output_directory.exists() or output_directory.is_symlink():
        raise ValueError("release output directory must not already exist")
    if source_directory.is_symlink() or not source_directory.is_dir():
        raise ValueError("source evidence directory must be a real directory")
    if container_directory.is_symlink() or not container_directory.is_dir():
        raise ValueError("container evidence directory must be a real directory")

    source_manifest = _read_object(
        source_directory / "release-manifest.json", "source release manifest"
    )
    container_manifest = _read_object(
        container_directory / "container-evidence.json", "container evidence"
    )
    if source_manifest.get("schema_version") != 2:
        raise ValueError("source release manifest schema is invalid")
    if container_manifest.get("schema_version") != 1:
        raise ValueError("container evidence schema is invalid")
    version = source_manifest.get("version")
    revision = source_manifest.get("revision")
    identity = (source_manifest.get("name"), version, revision)
    container_identity = (
        container_manifest.get("name"),
        container_manifest.get("version"),
        container_manifest.get("revision"),
    )
    if identity != container_identity:
        raise ValueError("source and container release identities do not match")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ValueError("release version is invalid")
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise ValueError("release revision is invalid")

    source_artifacts = source_manifest.get("artifacts")
    if not isinstance(source_artifacts, list) or len(source_artifacts) != 2:
        raise ValueError("source manifest must contain exactly two package artifacts")
    source_paths = [
        _validate_record(source_directory, record, "package artifact")
        for record in source_artifacts
    ]
    source_sbom = source_manifest.get("sbom")
    if not isinstance(source_sbom, dict):
        raise ValueError("source SBOM metadata is invalid")
    source_encrypted = _validate_record(
        source_directory, source_sbom.get("encrypted"), "encrypted ML-runtime SBOM"
    )
    source_recipient = _validate_sbom_metadata(
        source_encrypted,
        source_sbom,
        version=version,
        revision=revision,
        scope="ml-runtime",
    )

    container = container_manifest.get("container")
    if not isinstance(container, dict):
        raise ValueError("container metadata is invalid")
    image = container.get("image")
    digest = container.get("digest")
    platform = container.get("platform")
    reference = container.get("reference")
    if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
        raise ValueError("container digest is invalid")
    if (
        not isinstance(image, str)
        or not IMAGE_PATTERN.fullmatch(image)
        or reference != f"{image}@{digest}"
    ):
        raise ValueError("container reference is invalid")
    if not isinstance(platform, str) or not PLATFORM_PATTERN.fullmatch(platform):
        raise ValueError("container platform is invalid")
    container_sbom = container.get("sbom")
    if not isinstance(container_sbom, dict):
        raise ValueError("container SBOM metadata is invalid")
    container_encrypted = _validate_record(
        container_directory,
        container_sbom.get("encrypted"),
        "encrypted container SBOM",
    )
    container_recipient = _validate_sbom_metadata(
        container_encrypted,
        container_sbom,
        version=version,
        revision=revision,
        scope="container-image",
    )
    if source_recipient != container_recipient:
        raise ValueError("release SBOMs use different recipient keys")

    deployment_manifest = _regular_file(deployment_manifest)
    deployment_text = deployment_manifest.read_text(encoding="utf-8")
    if deployment_text.count(f"image: {reference}") != DEPLOYMENT_COUNT:
        raise ValueError("deployment manifest is not fully bound to the container digest")

    output_directory.mkdir(mode=0o755)
    copied_names: set[str] = set()
    copied_paths = [
        _copy_unique(path, output_directory, copied_names)
        for path in [*source_paths, source_encrypted, container_encrypted, deployment_manifest]
    ]
    final_manifest = json.loads(json.dumps(source_manifest))
    final_manifest["schema_version"] = 3
    final_manifest["container"] = container
    final_manifest["container"]["deployment_manifest"] = {
        "media_type": "application/yaml",
        "name": deployment_manifest.name,
        "sha256": _sha256(deployment_manifest),
        "size": deployment_manifest.stat().st_size,
    }
    manifest_path = output_directory / "release-manifest.json"
    manifest_path.write_text(
        json.dumps(final_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksums_path = output_directory / "SHA256SUMS"
    checksum_targets = sorted([*copied_paths, manifest_path], key=lambda path: path.name)
    checksums_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_targets),
        encoding="utf-8",
    )
    return manifest_path, checksums_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--container-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--deployment-manifest", type=Path, required=True)
    arguments = parser.parse_args()
    assemble_release_evidence(
        arguments.source_directory,
        arguments.container_directory,
        arguments.output_directory,
        arguments.deployment_manifest,
    )


if __name__ == "__main__":
    main()
