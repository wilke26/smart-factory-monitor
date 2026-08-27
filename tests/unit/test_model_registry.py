from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smart_factory.domain.model_registry import ModelRegistryEntry, ModelRegistryManifest


def entry(machine_id: str = "press-01") -> ModelRegistryEntry:
    return ModelRegistryEntry(
        machine_id=machine_id,
        model_id=f"model-{machine_id}",
        artifact_sha256="a" * 64,
    )


def test_accepts_strict_immutable_registry_manifest() -> None:
    manifest = ModelRegistryManifest(
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
        entries=(entry(),),
    )

    assert manifest.schema_version == 1
    with pytest.raises(ValidationError):
        manifest.entries = ()


@pytest.mark.parametrize(
    "entries",
    [(), (entry(), entry())],
)
def test_rejects_empty_or_duplicate_registry(entries: tuple[ModelRegistryEntry, ...]) -> None:
    with pytest.raises(ValidationError, match=r"at least one|unique"):
        ModelRegistryManifest(entries=entries)


def test_rejects_naive_manifest_timestamp() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        ModelRegistryManifest(
            created_at=datetime(2026, 8, 27),
            entries=(entry(),),
        )
