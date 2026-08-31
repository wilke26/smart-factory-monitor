from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "create_release_evidence.py"
VERSION = "0.20.0"
REVISION = "a" * 40


def _load_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location("create_release_evidence", SCRIPT_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _write_release_files(directory: Path, *, valid_sbom: bool = True) -> Path:
    stem = f"smart_factory_monitor-{VERSION}"
    (directory / f"{stem}-py3-none-any.whl").write_bytes(b"wheel")
    (directory / f"{stem}.tar.gz").write_bytes(b"source")
    sbom = {"spdxVersion": "SPDX-2.3", "packages": [{"name": "smart-factory-monitor"}]}
    if not valid_sbom:
        sbom["packages"] = []
    sbom_path = directory / f"{stem}.ml-runtime.spdx.json"
    sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
    return sbom_path


def _write_encrypted_sbom(directory: Path) -> Path:
    encrypted_path = directory / f"smart_factory_monitor-{VERSION}.ml-runtime.spdx.json.enc"
    encrypted_path.write_text(
        json.dumps(
            {
                "algorithm": "RSA-OAEP-SHA256+A256GCM",
                "authenticated_release": {
                    "name": f"smart_factory_monitor-{VERSION}.ml-runtime.spdx.json",
                    "revision": REVISION,
                    "version": VERSION,
                },
                "ciphertext": "Y2lwaGVydGV4dA==",
                "encrypted_key": "a2V5",
                "nonce": "bm9uY2U=",
                "recipient_key_sha256": "c" * 64,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    return encrypted_path


def test_creates_deterministic_manifest_and_checksums(tmp_path: Path) -> None:
    module = _load_script()
    sbom_path = _write_release_files(tmp_path)
    encrypted_sbom_path = _write_encrypted_sbom(tmp_path)

    manifest_path, checksums_path = module.create_release_evidence(
        tmp_path, VERSION, REVISION, sbom_path, encrypted_sbom_path
    )
    first_manifest = manifest_path.read_bytes()
    first_checksums = checksums_path.read_bytes()
    module.create_release_evidence(tmp_path, VERSION, REVISION, sbom_path, encrypted_sbom_path)

    manifest = json.loads(first_manifest)
    assert manifest["schema_version"] == 2
    assert manifest["version"] == VERSION
    assert manifest["revision"] == REVISION
    assert len(manifest["artifacts"]) == 2
    assert all(len(artifact["sha256"]) == 64 for artifact in manifest["artifacts"])
    assert manifest["sbom"]["scope"] == "ml-runtime"
    assert manifest["sbom"]["package_count"] == 1
    assert len(manifest["sbom"]["sha256"]) == 64
    assert manifest["sbom"]["encrypted"]["name"] == encrypted_sbom_path.name
    assert manifest["sbom"]["encrypted"]["algorithm"] == "RSA-OAEP-SHA256+A256GCM"
    assert manifest["sbom"]["encrypted"]["recipient_key_sha256"] == "c" * 64
    assert len(manifest["sbom"]["encrypted"]["sha256"]) == 64
    assert manifest_path.read_bytes() == first_manifest
    assert checksums_path.read_bytes() == first_checksums
    assert len(first_checksums.decode().splitlines()) == 4
    assert encrypted_sbom_path.name in first_checksums.decode()
    checksum_names = {
        line.split("  ", maxsplit=1)[1] for line in first_checksums.decode().splitlines()
    }
    assert sbom_path.name not in checksum_names


def test_rejects_invalid_sbom(tmp_path: Path) -> None:
    module = _load_script()
    sbom_path = _write_release_files(tmp_path, valid_sbom=False)
    encrypted_sbom_path = _write_encrypted_sbom(tmp_path)

    with pytest.raises(ValueError, match="at least one package"):
        module.create_release_evidence(tmp_path, VERSION, REVISION, sbom_path, encrypted_sbom_path)


@pytest.mark.parametrize("revision", ["abc", "A" * 40, "a" * 39])
def test_rejects_noncanonical_revision(tmp_path: Path, revision: str) -> None:
    module = _load_script()
    sbom_path = _write_release_files(tmp_path)
    encrypted_sbom_path = _write_encrypted_sbom(tmp_path)

    with pytest.raises(ValueError, match="full lowercase Git commit SHA"):
        module.create_release_evidence(tmp_path, VERSION, revision, sbom_path, encrypted_sbom_path)


def test_rejects_missing_encrypted_sbom(tmp_path: Path) -> None:
    module = _load_script()
    sbom_path = _write_release_files(tmp_path)

    with pytest.raises(ValueError, match="regular file"):
        module.create_release_evidence(
            tmp_path,
            VERSION,
            REVISION,
            sbom_path,
            tmp_path / "missing.spdx.json.enc",
        )


def test_rejects_encrypted_sbom_for_another_release(tmp_path: Path) -> None:
    module = _load_script()
    sbom_path = _write_release_files(tmp_path)
    encrypted_sbom_path = _write_encrypted_sbom(tmp_path)
    envelope = json.loads(encrypted_sbom_path.read_text(encoding="utf-8"))
    envelope["authenticated_release"]["revision"] = "d" * 40
    encrypted_sbom_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="identity does not match"):
        module.create_release_evidence(tmp_path, VERSION, REVISION, sbom_path, encrypted_sbom_path)
