from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "deploy" / "kubernetes" / "render-release.py"


def _load_script() -> ModuleType:
    specification = importlib.util.spec_from_file_location("render_release", SCRIPT_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_bind_image_digest_replaces_mutable_tag() -> None:
    module = _load_script()
    source = """images:
  - name: smart-factory-monitor
    newName: old.example/smart-factory-monitor
    newTag: 0.18.0
"""
    digest = "sha256:" + "a" * 64

    rendered = module._bind_image_digest(source, "registry.example/smart-factory-monitor", digest)

    assert "    newName: registry.example/smart-factory-monitor" in rendered
    assert f"    digest: {digest}" in rendered
    assert "newTag:" not in rendered


@pytest.mark.parametrize(
    ("image", "digest"),
    [
        ("registry.example/smart-factory-monitor:latest", "sha256:" + "a" * 64),
        ("registry.example/smart-factory-monitor", "sha256:not-a-digest"),
        ("REGISTRY.example/smart-factory-monitor", "sha256:" + "a" * 64),
    ],
)
def test_rejects_mutable_or_malformed_image_references(image: str, digest: str) -> None:
    module = _load_script()

    with pytest.raises(ValueError):
        module._validated_reference(image, digest)
