from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import smart_factory.release_verification as verification_module
from smart_factory.release_evidence_crypto import encrypt_release_evidence
from smart_factory.release_signature import (
    generate_signing_key_pair,
    release_signature_name,
    sign_release_bundle,
)
from smart_factory.release_signature import (
    main as signature_main,
)
from smart_factory.release_verification import main, verify_release_bundle

VERSION = "0.26.0"
REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64
IMAGE = "ghcr.io/wilke26/smart-factory-monitor"
REFERENCE = f"{IMAGE}@{DIGEST}"
PASSWORD = b"test-release-key-password"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path, media_type: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": path.name,
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }
    if media_type is not None:
        result["media_type"] = media_type
    return result


def _write_checksums(directory: Path) -> None:
    targets = sorted(
        (
            path
            for path in directory.iterdir()
            if path.name != "SHA256SUMS" and not path.name.endswith(".release-signature.json")
        ),
        key=lambda path: path.name,
    )
    (directory / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in targets),
        encoding="utf-8",
    )


def _rewrite_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    (directory / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_checksums(directory)


@pytest.fixture(scope="module")
def release_fixture(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    root = tmp_path_factory.mktemp("release-bundle")
    bundle = root / "bundle"
    bundle.mkdir()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_path = root / "private.pem"
    public_path = root / "public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(PASSWORD),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    stem = f"smart_factory_monitor-{VERSION}"
    wheel = bundle / f"{stem}-py3-none-any.whl"
    source = bundle / f"{stem}.tar.gz"
    deployment = bundle / f"{stem}.kubernetes.yaml"
    wheel.write_bytes(b"test wheel bytes\n")
    source.write_bytes(b"test source archive bytes\n")
    deployment.write_text(
        "\n---\n".join(
            f"apiVersion: apps/v1\nkind: Deployment\nspec:\n  template:\n    spec:\n"
            f"      containers:\n        - image: {REFERENCE}\n"
            for _ in range(3)
        ),
        encoding="utf-8",
    )

    sbom_metadata: dict[str, dict[str, Any]] = {}
    for scope, suffix, package_count in (
        ("ml-runtime", "ml-runtime", 2),
        ("container-image", "container", 3),
    ):
        plaintext = root / f"{stem}.{suffix}.spdx.json"
        plaintext.write_text(
            json.dumps(
                {
                    "packages": [{"name": f"package-{index}"} for index in range(package_count)],
                    "spdxVersion": "SPDX-2.3",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        encrypted = bundle / f"{plaintext.name}.enc"
        encrypt_release_evidence(plaintext, encrypted, public_path, VERSION, REVISION)
        envelope = json.loads(encrypted.read_text(encoding="utf-8"))
        sbom_metadata[scope] = {
            "encrypted": {
                **_record(encrypted),
                "algorithm": "RSA-OAEP-SHA256+A256GCM",
                "recipient_key_sha256": envelope["recipient_key_sha256"],
            },
            "format": "SPDX-2.x",
            "name": plaintext.name,
            "package_count": package_count,
            "scope": scope,
            "sha256": _sha256(plaintext),
        }

    manifest = {
        "artifacts": [
            _record(wheel, "application/zip"),
            _record(source, "application/gzip"),
        ],
        "container": {
            "deployment_manifest": _record(deployment, "application/yaml"),
            "digest": DIGEST,
            "image": IMAGE,
            "platform": "linux/amd64",
            "reference": REFERENCE,
            "sbom": sbom_metadata["container-image"],
        },
        "name": "smart-factory-monitor",
        "revision": REVISION,
        "sbom": sbom_metadata["ml-runtime"],
        "schema_version": 3,
        "version": VERSION,
    }
    _rewrite_manifest(bundle, manifest)
    return bundle, private_path, public_path


def _copy_bundle(source: Path, destination: Path) -> Path:
    return Path(shutil.copytree(source, destination))


def _signing_keys(directory: Path) -> tuple[Path, Path]:
    directory.mkdir()
    private_path = directory / "release-signing-private.pem"
    public_path = directory / "release-signing-public.pem"
    generate_signing_key_pair(private_path, public_path, PASSWORD)
    return private_path, public_path


def _sign(
    directory: Path,
    signature_path: Path,
    private_key_path: Path,
    password: bytes = PASSWORD,
    *,
    expected_version: str = VERSION,
    expected_revision: str = REVISION,
    expected_image_reference: str = REFERENCE,
) -> Path:
    return sign_release_bundle(
        directory,
        signature_path,
        private_key_path,
        password,
        expected_version=expected_version,
        expected_revision=expected_revision,
        expected_image_reference=expected_image_reference,
    )


def test_verifies_complete_bundle_without_network_or_private_material(
    release_fixture: tuple[Path, Path, Path],
) -> None:
    bundle, _, _ = release_fixture

    result = verify_release_bundle(
        bundle,
        expected_version=VERSION,
        expected_revision=REVISION,
        expected_image_reference=REFERENCE,
    )

    assert result["status"] == "verified"
    assert result["files_checked"] == 6
    assert result["container"] == {"platform": "linux/amd64", "reference": REFERENCE}


def test_verifies_public_recipient_and_recovers_both_private_sboms(
    release_fixture: tuple[Path, Path, Path],
) -> None:
    bundle, private_path, public_path = release_fixture

    result = verify_release_bundle(
        bundle,
        public_key_path=public_path,
        private_key_path=private_path,
        private_key_password=PASSWORD,
    )

    assert result["public_key_verified"] is True
    assert result["recovered_sboms"]["ml-runtime"]["package_count"] == 2
    assert result["recovered_sboms"]["container-image"]["package_count"] == 3
    assert not list(bundle.glob("*.spdx.json"))


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("expected_version", "0.23.1", "expected version"),
        ("expected_revision", "c" * 40, "expected revision"),
        (
            "expected_image_reference",
            f"ghcr.io/example/other@{DIGEST}",
            "expected image",
        ),
    ],
)
def test_rejects_unexpected_release_identity(
    release_fixture: tuple[Path, Path, Path],
    keyword: str,
    value: str,
    message: str,
) -> None:
    bundle, _, _ = release_fixture

    with pytest.raises(ValueError, match=message):
        verify_release_bundle(bundle, **{keyword: value})


def test_rejects_modified_artifact(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "modified")
    next(candidate.glob("*.whl")).write_bytes(b"modified")

    with pytest.raises(ValueError, match="recorded identity"):
        verify_release_bundle(candidate)


def test_rejects_unexpected_files_and_symbolic_links(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    extra = _copy_bundle(bundle, tmp_path / "extra")
    (extra / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="membership"):
        verify_release_bundle(extra)

    linked = _copy_bundle(bundle, tmp_path / "linked")
    (linked / "link").symlink_to(linked / "release-manifest.json")
    with pytest.raises(ValueError, match="regular file"):
        verify_release_bundle(linked)


def test_rejects_encrypted_sbom_for_another_release(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "wrong-envelope")
    manifest = json.loads((candidate / "release-manifest.json").read_text(encoding="utf-8"))
    encrypted_path = candidate / manifest["sbom"]["encrypted"]["name"]
    envelope = json.loads(encrypted_path.read_text(encoding="utf-8"))
    envelope["authenticated_release"]["revision"] = "d" * 40
    encrypted_path.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    manifest["sbom"]["encrypted"].update(_record(encrypted_path))
    _rewrite_manifest(candidate, manifest)

    with pytest.raises(ValueError, match="identity"):
        verify_release_bundle(candidate)


def test_rejects_deployment_not_bound_to_release_digest(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "mutable-deployment")
    manifest = json.loads((candidate / "release-manifest.json").read_text(encoding="utf-8"))
    deployment_path = candidate / manifest["container"]["deployment_manifest"]["name"]
    deployment_path.write_text(
        deployment_path.read_text(encoding="utf-8").replace(REFERENCE, f"{IMAGE}:{VERSION}", 1),
        encoding="utf-8",
    )
    manifest["container"]["deployment_manifest"] = _record(deployment_path, "application/yaml")
    _rewrite_manifest(candidate, manifest)

    with pytest.raises(ValueError, match="fully bound"):
        verify_release_bundle(candidate)


def test_rejects_checksum_path_traversal(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "traversal")
    sums = candidate / "SHA256SUMS"
    first, *rest = sums.read_text(encoding="utf-8").splitlines()
    digest, _ = first.split("  ", maxsplit=1)
    sums.write_text("\n".join([f"{digest}  ../outside", *rest]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid line"):
        verify_release_bundle(candidate)


def test_rejects_wrong_public_key(tmp_path: Path, release_fixture: tuple[Path, Path, Path]) -> None:
    bundle, _, _ = release_fixture
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=3072).public_key()
    wrong_public_path = tmp_path / "wrong-public.pem"
    wrong_public_path.write_bytes(
        wrong_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    with pytest.raises(ValueError, match="does not match"):
        verify_release_bundle(bundle, public_key_path=wrong_public_path)


def test_cli_emits_machine_readable_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    release_fixture: tuple[Path, Path, Path],
) -> None:
    bundle, _, _ = release_fixture
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smart-factory-verify-release",
            str(bundle),
            "--expected-version",
            VERSION,
            "--json",
        ],
    )

    main()

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "verified"
    assert result["version"] == VERSION


def test_signs_and_authenticates_the_complete_release_bundle(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "signed")
    private_path, public_path = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)

    _sign(candidate, signature_path, private_path)
    with pytest.raises(ValueError, match="membership"):
        verify_release_bundle(candidate)
    result = verify_release_bundle(
        candidate,
        signature_path=signature_path,
        signing_public_key_path=public_path,
    )

    assert private_path.stat().st_mode & 0o777 == 0o600
    assert result["release_signature"]["algorithm"] == "Ed25519"
    assert len(result["release_signature"]["signing_key_sha256"]) == 64


@pytest.mark.parametrize(
    ("expected_version", "expected_revision", "expected_image_reference", "message"),
    (
        ("9.9.9", REVISION, REFERENCE, "version does not match"),
        (VERSION, "c" * 40, REFERENCE, "revision does not match"),
        (
            VERSION,
            REVISION,
            f"{IMAGE}@sha256:{'d' * 64}",
            "container reference does not match",
        ),
    ),
)
def test_refuses_to_sign_without_the_expected_release_identity(
    tmp_path: Path,
    release_fixture: tuple[Path, Path, Path],
    expected_version: str,
    expected_revision: str,
    expected_image_reference: str,
    message: str,
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "identity-mismatch")
    private_path, _ = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)

    with pytest.raises(ValueError, match=message):
        _sign(
            candidate,
            signature_path,
            private_path,
            expected_version=expected_version,
            expected_revision=expected_revision,
            expected_image_reference=expected_image_reference,
        )

    assert not signature_path.exists()


def test_signs_a_stable_snapshot_when_source_changes_after_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_fixture: tuple[Path, Path, Path],
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "source-swap")
    private_path, public_path = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)
    original_verify = verification_module.verify_release_bundle

    def verify_then_replace(directory: Path, **kwargs: object) -> dict[str, Any]:
        result = original_verify(directory, **kwargs)
        manifest = json.loads((candidate / "release-manifest.json").read_text(encoding="utf-8"))
        wheel = candidate / manifest["artifacts"][0]["name"]
        wheel.write_bytes(b"replacement with the same declared release identity")
        manifest["artifacts"][0] = _record(wheel, "application/zip")
        _rewrite_manifest(candidate, manifest)
        return result

    monkeypatch.setattr(verification_module, "verify_release_bundle", verify_then_replace)
    _sign(candidate, signature_path, private_path)

    with pytest.raises(ValueError, match="different release evidence"):
        verify_release_bundle(
            candidate,
            signature_path=signature_path,
            signing_public_key_path=public_path,
        )


def test_refuses_to_sign_without_no_follow_file_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_fixture: tuple[Path, Path, Path],
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "unsupported-no-follow")
    private_path, _ = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)
    monkeypatch.delattr(os, "O_NOFOLLOW")

    with pytest.raises(ValueError, match="requires no-follow"):
        _sign(candidate, signature_path, private_path)

    assert not signature_path.exists()


def test_rejects_tampered_release_signature(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "tampered-signature")
    private_path, public_path = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)
    _sign(candidate, signature_path, private_path)
    document = json.loads(signature_path.read_text(encoding="utf-8"))
    encoded = document["signature"]
    document["signature"] = ("A" if encoded[0] != "A" else "B") + encoded[1:]
    signature_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="authentication failed"):
        verify_release_bundle(
            candidate,
            signature_path=signature_path,
            signing_public_key_path=public_path,
        )


def test_rejects_internally_rechecksummed_bundle_after_signing(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "rechecksummed")
    private_path, public_path = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)
    _sign(candidate, signature_path, private_path)
    manifest = json.loads((candidate / "release-manifest.json").read_text(encoding="utf-8"))
    wheel = candidate / manifest["artifacts"][0]["name"]
    wheel.write_bytes(b"attacker-replaced-wheel")
    manifest["artifacts"][0] = _record(wheel, "application/zip")
    _rewrite_manifest(candidate, manifest)

    with pytest.raises(ValueError, match="different release evidence"):
        verify_release_bundle(
            candidate,
            signature_path=signature_path,
            signing_public_key_path=public_path,
        )


def test_rejects_signature_replayed_for_another_revision(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "replayed")
    private_path, public_path = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)
    _sign(candidate, signature_path, private_path)
    manifest = json.loads((candidate / "release-manifest.json").read_text(encoding="utf-8"))
    manifest["revision"] = "e" * 40
    for metadata in (manifest["sbom"], manifest["container"]["sbom"]):
        encrypted_path = candidate / metadata["encrypted"]["name"]
        envelope = json.loads(encrypted_path.read_text(encoding="utf-8"))
        envelope["authenticated_release"]["revision"] = manifest["revision"]
        encrypted_path.write_text(json.dumps(envelope), encoding="utf-8")
        metadata["encrypted"].update(_record(encrypted_path))
    _rewrite_manifest(candidate, manifest)

    with pytest.raises(ValueError, match="different release evidence"):
        verify_release_bundle(
            candidate,
            signature_path=signature_path,
            signing_public_key_path=public_path,
        )


def test_rejects_wrong_release_signing_key(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "wrong-signing-key")
    private_path, _ = _signing_keys(tmp_path / "keys")
    _, wrong_public_path = _signing_keys(tmp_path / "other-keys")
    signature_path = candidate / release_signature_name(VERSION)
    _sign(candidate, signature_path, private_path)

    with pytest.raises(ValueError, match="different release evidence or key"):
        verify_release_bundle(
            candidate,
            signature_path=signature_path,
            signing_public_key_path=wrong_public_path,
        )


def test_refuses_unencrypted_or_overwritten_release_signing_material(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "write-once")
    private_path, _ = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)

    with pytest.raises(ValueError, match="password must not be empty"):
        _sign(candidate, signature_path, private_path, b"")
    with pytest.raises(ValueError):
        _sign(candidate, signature_path, private_path, b"wrong-password")
    _sign(candidate, signature_path, private_path)
    with pytest.raises(ValueError, match="refusing to replace"):
        _sign(candidate, signature_path, private_path)


def test_release_signature_cli_generates_keys_and_signs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    release_fixture: tuple[Path, Path, Path],
) -> None:
    bundle, _, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "cli-signed")
    private_path = tmp_path / "cli-private.pem"
    public_path = tmp_path / "cli-public.pem"
    signature_path = candidate / release_signature_name(VERSION)
    monkeypatch.setenv("TEST_RELEASE_SIGNING_PASSWORD", PASSWORD.decode("ascii"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smart-factory-release-signature",
            "generate-key",
            "--private-key",
            str(private_path),
            "--public-key",
            str(public_path),
            "--private-key-password-env",
            "TEST_RELEASE_SIGNING_PASSWORD",
        ],
    )
    signature_main()
    assert "Release-signing key SHA-256" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smart-factory-release-signature",
            "sign",
            str(candidate),
            "--output",
            str(signature_path),
            "--private-key",
            str(private_path),
            "--private-key-password-env",
            "TEST_RELEASE_SIGNING_PASSWORD",
            "--expected-version",
            VERSION,
            "--expected-revision",
            REVISION,
            "--expected-image-reference",
            REFERENCE,
        ],
    )
    signature_main()
    assert "Created release signature" in capsys.readouterr().out

    result = verify_release_bundle(
        candidate,
        signature_path=signature_path,
        signing_public_key_path=public_path,
    )
    assert result["release_signature"]["algorithm"] == "Ed25519"


def test_requires_signature_and_public_key_together(
    tmp_path: Path, release_fixture: tuple[Path, Path, Path]
) -> None:
    bundle, _, _ = release_fixture

    with pytest.raises(ValueError, match="provided together"):
        verify_release_bundle(bundle, signature_path=tmp_path / release_signature_name(VERSION))


def test_rejects_bad_signature_before_private_sbom_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_fixture: tuple[Path, Path, Path],
) -> None:
    bundle, recovery_private_path, _ = release_fixture
    candidate = _copy_bundle(bundle, tmp_path / "authenticate-first")
    signing_private_path, signing_public_path = _signing_keys(tmp_path / "keys")
    signature_path = candidate / release_signature_name(VERSION)
    _sign(candidate, signature_path, signing_private_path)
    signature_path.write_text("{}\n", encoding="utf-8")

    def unexpected_recovery(*args: object, **kwargs: object) -> dict[str, dict[str, Any]]:
        raise AssertionError("private SBOM recovery ran before signature authentication")

    monkeypatch.setattr(verification_module, "_recover_sboms", unexpected_recovery)
    with pytest.raises(ValueError, match="signature document is invalid"):
        verify_release_bundle(
            candidate,
            private_key_path=recovery_private_path,
            private_key_password=PASSWORD,
            signature_path=signature_path,
            signing_public_key_path=signing_public_path,
        )
