#!/usr/bin/env python3
"""Create deterministic checksums and metadata for package release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MEDIA_TYPES = {
    ".whl": "application/zip",
    ".tar.gz": "application/gzip",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"release artifact must be a regular file: {path.name}")
    return path


def _validate_sbom(path: Path) -> int:
    _regular_file(path)
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("SBOM must be valid UTF-8 JSON") from error
    if not isinstance(document, dict) or not str(document.get("spdxVersion", "")).startswith(
        "SPDX-2."
    ):
        raise ValueError("SBOM must be an SPDX 2.x JSON document")
    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("SBOM must contain at least one package")
    return len(packages)


def _validate_encrypted_sbom(
    path: Path, *, version: str, revision: str, sbom_name: str
) -> dict[str, str]:
    _regular_file(path)
    try:
        envelope: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("encrypted SBOM must be valid UTF-8 JSON") from error
    if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
        raise ValueError("encrypted SBOM envelope schema is invalid")
    algorithm = envelope.get("algorithm")
    recipient_key_sha256 = envelope.get("recipient_key_sha256")
    identity = envelope.get("authenticated_release")
    if algorithm != "RSA-OAEP-SHA256+A256GCM":
        raise ValueError("encrypted SBOM algorithm is invalid")
    if not isinstance(recipient_key_sha256, str) or not SHA256_PATTERN.fullmatch(
        recipient_key_sha256
    ):
        raise ValueError("encrypted SBOM recipient key fingerprint is invalid")
    if identity != {"name": sbom_name, "revision": revision, "version": version}:
        raise ValueError("encrypted SBOM identity does not match the release")
    for field in ("ciphertext", "encrypted_key", "nonce"):
        if not isinstance(envelope.get(field), str) or not envelope[field]:
            raise ValueError(f"encrypted SBOM field {field} is invalid")
    return {"algorithm": algorithm, "recipient_key_sha256": recipient_key_sha256}


def _media_type(path: Path) -> str:
    for suffix, media_type in MEDIA_TYPES.items():
        if path.name.endswith(suffix):
            return media_type
    raise ValueError(f"unsupported release artifact: {path.name}")


def create_release_evidence(
    directory: Path,
    version: str,
    revision: str,
    sbom_path: Path,
    encrypted_sbom_path: Path,
) -> tuple[Path, Path]:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must use numeric major.minor.patch format")
    if not REVISION_PATTERN.fullmatch(revision):
        raise ValueError("revision must be a full lowercase Git commit SHA")
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("release directory must be a real directory")

    stem = f"smart_factory_monitor-{version}"
    primary_artifacts = [
        _regular_file(directory / f"{stem}-py3-none-any.whl"),
        _regular_file(directory / f"{stem}.tar.gz"),
    ]
    sbom_package_count = _validate_sbom(sbom_path)
    encrypted_metadata = _validate_encrypted_sbom(
        encrypted_sbom_path,
        version=version,
        revision=revision,
        sbom_name=sbom_path.name,
    )

    records = [
        {
            "media_type": _media_type(path),
            "name": path.name,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        for path in primary_artifacts
    ]
    manifest = {
        "artifacts": records,
        "name": "smart-factory-monitor",
        "revision": revision,
        "sbom": {
            "encrypted": {
                "algorithm": encrypted_metadata["algorithm"],
                "name": encrypted_sbom_path.name,
                "recipient_key_sha256": encrypted_metadata["recipient_key_sha256"],
                "sha256": _sha256(encrypted_sbom_path),
                "size": encrypted_sbom_path.stat().st_size,
            },
            "format": "SPDX-2.x",
            "name": sbom_path.name,
            "package_count": sbom_package_count,
            "scope": "ml-runtime",
            "sha256": _sha256(sbom_path),
        },
        "schema_version": 2,
        "version": version,
    }
    manifest_path = directory / "release-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    checksums_path = directory / "SHA256SUMS"
    checksum_targets = sorted(
        [*primary_artifacts, encrypted_sbom_path, manifest_path], key=lambda path: path.name
    )
    checksums_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_targets),
        encoding="utf-8",
    )
    return manifest_path, checksums_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--encrypted-sbom", type=Path, required=True)
    arguments = parser.parse_args()
    create_release_evidence(
        arguments.directory,
        arguments.version,
        arguments.revision,
        arguments.sbom,
        arguments.encrypted_sbom,
    )


if __name__ == "__main__":
    main()
