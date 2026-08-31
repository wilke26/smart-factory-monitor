from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "release_evidence_crypto.py"
VERSION = "0.20.0"
REVISION = "b" * 40


def _load_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location("release_evidence_crypto", SCRIPT_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _write_key_pair(directory: Path, *, key_size: int = 3072) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    private_path = directory / "private.pem"
    public_path = directory / "public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def test_encrypts_and_recovers_authenticated_sbom(tmp_path: Path) -> None:
    module = _load_script()
    private_path, public_path = _write_key_pair(tmp_path)
    sbom_path = tmp_path / "smart_factory_monitor-0.20.0.ml-runtime.spdx.json"
    sbom_content = b'{"packages":[{"name":"smart-factory-monitor"}]}\n'
    sbom_path.write_bytes(sbom_content)
    encrypted_path = tmp_path / f"{sbom_path.name}.enc"
    recovered_path = tmp_path / "recovered.spdx.json"

    module.encrypt_release_evidence(sbom_path, encrypted_path, public_path, VERSION, REVISION)
    envelope = json.loads(encrypted_path.read_text(encoding="utf-8"))
    assert envelope["algorithm"] == "RSA-OAEP-SHA256+A256GCM"
    assert envelope["authenticated_release"] == {
        "name": sbom_path.name,
        "revision": REVISION,
        "version": VERSION,
    }
    assert len(envelope["recipient_key_sha256"]) == 64
    assert sbom_content not in encrypted_path.read_bytes()

    module.decrypt_release_evidence(encrypted_path, recovered_path, private_path, VERSION, REVISION)
    assert recovered_path.read_bytes() == sbom_content
    assert recovered_path.stat().st_mode & 0o777 == 0o600


def test_rejects_tampering_and_wrong_release_identity(tmp_path: Path) -> None:
    module = _load_script()
    private_path, public_path = _write_key_pair(tmp_path)
    sbom_path = tmp_path / "runtime.spdx.json"
    sbom_path.write_text('{"packages":[{}]}', encoding="utf-8")
    encrypted_path = tmp_path / "runtime.spdx.json.enc"
    module.encrypt_release_evidence(sbom_path, encrypted_path, public_path, VERSION, REVISION)

    with pytest.raises(ValueError, match="different release"):
        module.decrypt_release_evidence(
            encrypted_path,
            tmp_path / "wrong-version.json",
            private_path,
            "0.20.1",
            REVISION,
        )

    envelope = json.loads(encrypted_path.read_text(encoding="utf-8"))
    ciphertext = envelope["ciphertext"]
    envelope["ciphertext"] = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    encrypted_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="authentication failed"):
        module.decrypt_release_evidence(
            encrypted_path,
            tmp_path / "tampered.json",
            private_path,
            VERSION,
            REVISION,
        )


def test_rejects_wrong_recipient_private_key(tmp_path: Path) -> None:
    module = _load_script()
    _, public_path = _write_key_pair(tmp_path)
    wrong_private_path, _ = _write_key_pair(tmp_path / "other")
    sbom_path = tmp_path / "runtime.spdx.json"
    sbom_path.write_text('{"packages":[{}]}', encoding="utf-8")
    encrypted_path = tmp_path / "runtime.spdx.json.enc"
    module.encrypt_release_evidence(sbom_path, encrypted_path, public_path, VERSION, REVISION)

    with pytest.raises(ValueError, match="different recipient key"):
        module.decrypt_release_evidence(
            encrypted_path,
            tmp_path / "wrong-key.json",
            wrong_private_path,
            VERSION,
            REVISION,
        )


def test_rejects_weak_recipient_key_and_existing_output(tmp_path: Path) -> None:
    module = _load_script()
    _, public_path = _write_key_pair(tmp_path, key_size=2048)
    sbom_path = tmp_path / "runtime.spdx.json"
    sbom_path.write_text('{"packages":[{}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="at least 3072 bits"):
        module.encrypt_release_evidence(
            sbom_path,
            tmp_path / "runtime.spdx.json.enc",
            public_path,
            VERSION,
            REVISION,
        )

    existing_path = tmp_path / "existing.enc"
    existing_path.write_text("existing", encoding="utf-8")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    strong_public_path = tmp_path / "strong-public.pem"
    strong_public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    with pytest.raises(ValueError, match="refusing to replace"):
        module.encrypt_release_evidence(
            sbom_path, existing_path, strong_public_path, VERSION, REVISION
        )
