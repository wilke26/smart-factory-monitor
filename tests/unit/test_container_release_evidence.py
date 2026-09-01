from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.21.0"
REVISION = "a" * 40
IMAGE = "ghcr.io/wilke26/smart-factory-monitor"
DIGEST = f"sha256:{'b' * 64}"
PLATFORM = "linux/amd64"


def _load_script(name: str) -> ModuleType:
    path = REPOSITORY_ROOT / "scripts" / f"{name}.py"
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _write_sbom(path: Path, name: str) -> Path:
    sbom_path = path / name
    sbom_path.write_text(
        json.dumps({"packages": [{"name": "python"}], "spdxVersion": "SPDX-2.3"}),
        encoding="utf-8",
    )
    return sbom_path


def _write_encrypted_sbom(path: Path, sbom_path: Path, *, recipient: str = "c" * 64) -> Path:
    encrypted_path = path / f"{sbom_path.name}.enc"
    encrypted_path.write_text(
        json.dumps(
            {
                "algorithm": "RSA-OAEP-SHA256+A256GCM",
                "authenticated_release": {
                    "name": sbom_path.name,
                    "revision": REVISION,
                    "version": VERSION,
                },
                "ciphertext": "Y2lwaGVydGV4dA==",
                "encrypted_key": "a2V5",
                "nonce": "bm9uY2U=",
                "recipient_key_sha256": recipient,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    return encrypted_path


def _create_source_evidence(directory: Path) -> None:
    module = _load_script("create_release_evidence")
    stem = f"smart_factory_monitor-{VERSION}"
    (directory / f"{stem}-py3-none-any.whl").write_bytes(b"wheel")
    (directory / f"{stem}.tar.gz").write_bytes(b"source")
    sbom_path = _write_sbom(directory, f"{stem}.ml-runtime.spdx.json")
    encrypted_path = _write_encrypted_sbom(directory, sbom_path)
    module.create_release_evidence(directory, VERSION, REVISION, sbom_path, encrypted_path)
    sbom_path.unlink()


def _create_container_evidence(directory: Path, *, recipient: str = "c" * 64) -> None:
    module = _load_script("create_container_evidence")
    sbom_path = _write_sbom(directory, f"smart_factory_monitor-{VERSION}.container.spdx.json")
    encrypted_path = _write_encrypted_sbom(directory, sbom_path, recipient=recipient)
    module.create_container_evidence(
        directory,
        VERSION,
        REVISION,
        IMAGE,
        DIGEST,
        PLATFORM,
        sbom_path,
        encrypted_path,
    )
    sbom_path.unlink()


def test_creates_digest_bound_container_evidence(tmp_path: Path) -> None:
    module = _load_script("create_container_evidence")
    sbom_path = _write_sbom(tmp_path, f"smart_factory_monitor-{VERSION}.container.spdx.json")
    encrypted_path = _write_encrypted_sbom(tmp_path, sbom_path)

    evidence_path, checksums_path = module.create_container_evidence(
        tmp_path,
        VERSION,
        REVISION,
        IMAGE,
        DIGEST,
        PLATFORM,
        sbom_path,
        encrypted_path,
    )

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == 1
    assert evidence["container"]["reference"] == f"{IMAGE}@{DIGEST}"
    assert evidence["container"]["platform"] == PLATFORM
    assert evidence["container"]["sbom"]["package_count"] == 1
    assert evidence["container"]["sbom"]["encrypted"]["name"] == encrypted_path.name
    assert len(checksums_path.read_text(encoding="utf-8").splitlines()) == 2


def test_rejects_invalid_container_digest(tmp_path: Path) -> None:
    module = _load_script("create_container_evidence")
    sbom_path = _write_sbom(tmp_path, "container.spdx.json")
    encrypted_path = _write_encrypted_sbom(tmp_path, sbom_path)

    with pytest.raises(ValueError, match="lowercase sha256 digest"):
        module.create_container_evidence(
            tmp_path,
            VERSION,
            REVISION,
            IMAGE,
            "sha256:1234",
            PLATFORM,
            sbom_path,
            encrypted_path,
        )


def test_rejects_unsupported_container_platform(tmp_path: Path) -> None:
    module = _load_script("create_container_evidence")
    sbom_path = _write_sbom(tmp_path, "container.spdx.json")
    encrypted_path = _write_encrypted_sbom(tmp_path, sbom_path)

    with pytest.raises(ValueError, match="linux/amd64 or linux/arm64"):
        module.create_container_evidence(
            tmp_path,
            VERSION,
            REVISION,
            IMAGE,
            DIGEST,
            "linux/s390x",
            sbom_path,
            encrypted_path,
        )


def test_rejects_container_ciphertext_for_another_release(tmp_path: Path) -> None:
    module = _load_script("create_container_evidence")
    sbom_path = _write_sbom(tmp_path, "container.spdx.json")
    encrypted_path = _write_encrypted_sbom(tmp_path, sbom_path)
    envelope = json.loads(encrypted_path.read_text(encoding="utf-8"))
    envelope["authenticated_release"]["revision"] = "d" * 40
    encrypted_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="identity does not match"):
        module.create_container_evidence(
            tmp_path,
            VERSION,
            REVISION,
            IMAGE,
            DIGEST,
            PLATFORM,
            sbom_path,
            encrypted_path,
        )


def test_assembles_source_container_and_deployment_evidence(tmp_path: Path) -> None:
    module = _load_script("assemble_release_evidence")
    source = tmp_path / "source"
    container = tmp_path / "container"
    source.mkdir()
    container.mkdir()
    _create_source_evidence(source)
    _create_container_evidence(container)
    deployment = tmp_path / f"smart_factory_monitor-{VERSION}.kubernetes.yaml"
    deployment.write_text(f"image: {IMAGE}@{DIGEST}\n" * 3, encoding="utf-8")
    output = tmp_path / "release"

    manifest_path, checksums_path = module.assemble_release_evidence(
        source, container, output, deployment
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 3
    assert manifest["container"]["reference"] == f"{IMAGE}@{DIGEST}"
    assert manifest["container"]["deployment_manifest"]["name"] == deployment.name
    checksum_names = {
        line.split("  ", maxsplit=1)[1]
        for line in checksums_path.read_text(encoding="utf-8").splitlines()
    }
    assert len(checksum_names) == 6
    assert not any(output.glob("*.spdx.json"))
    assert {path.name for path in output.iterdir()} == checksum_names | {"SHA256SUMS"}


def test_assembly_rejects_deployment_not_bound_to_every_workload(tmp_path: Path) -> None:
    module = _load_script("assemble_release_evidence")
    source = tmp_path / "source"
    container = tmp_path / "container"
    source.mkdir()
    container.mkdir()
    _create_source_evidence(source)
    _create_container_evidence(container)
    deployment = tmp_path / "deployment.yaml"
    deployment.write_text(f"image: {IMAGE}@{DIGEST}\n" * 2, encoding="utf-8")

    with pytest.raises(ValueError, match="not fully bound"):
        module.assemble_release_evidence(source, container, tmp_path / "release", deployment)


def test_assembly_rejects_different_sbom_recipient_keys(tmp_path: Path) -> None:
    module = _load_script("assemble_release_evidence")
    source = tmp_path / "source"
    container = tmp_path / "container"
    source.mkdir()
    container.mkdir()
    _create_source_evidence(source)
    _create_container_evidence(container, recipient="d" * 64)
    deployment = tmp_path / "deployment.yaml"
    deployment.write_text(f"image: {IMAGE}@{DIGEST}\n" * 3, encoding="utf-8")

    with pytest.raises(ValueError, match="different recipient keys"):
        module.assemble_release_evidence(source, container, tmp_path / "release", deployment)


def test_assembly_rejects_modified_source_artifact(tmp_path: Path) -> None:
    module = _load_script("assemble_release_evidence")
    source = tmp_path / "source"
    container = tmp_path / "container"
    source.mkdir()
    container.mkdir()
    _create_source_evidence(source)
    _create_container_evidence(container)
    wheel = source / f"smart_factory_monitor-{VERSION}-py3-none-any.whl"
    wheel.write_bytes(b"modified")
    deployment = tmp_path / "deployment.yaml"
    deployment.write_text(f"image: {IMAGE}@{DIGEST}\n" * 3, encoding="utf-8")

    with pytest.raises(ValueError, match="does not match its recorded identity"):
        module.assemble_release_evidence(source, container, tmp_path / "release", deployment)
