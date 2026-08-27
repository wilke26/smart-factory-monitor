from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from unittest.mock import ANY, Mock, call, patch

import pytest

from smart_factory.application.services.model_promotion import PromotionCandidate
from smart_factory.domain.model_registry import ModelRegistryEntry, ModelRegistryManifest
from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactVerifier,
    artifact_signature_path,
)
from smart_factory.infrastructure.ml.isolation_forest import MlArtifactError
from smart_factory.infrastructure.ml.registry import (
    FilesystemModelRegistryPublisher,
    MachineModelRegistry,
)


def reading(machine_id: str) -> TelemetryReading:
    return TelemetryReading(
        machine_id=machine_id,
        timestamp=datetime(2026, 8, 24, tzinfo=UTC),
        temperature_c=68.0,
        vibration_mm_s=2.5,
        power_kw=17.0,
        production_rate=44,
    )


def write_active_manifest(directory: Path, payloads: dict[str, bytes]) -> ModelRegistryManifest:
    entries = []
    for machine_id, payload in payloads.items():
        digest = sha256(payload).hexdigest()
        path = directory / "versions" / machine_id / f"{digest}.joblib"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        entries.append(
            ModelRegistryEntry(
                machine_id=machine_id,
                model_id=f"model-{machine_id}",
                artifact_sha256=digest,
            )
        )
    manifest = ModelRegistryManifest(entries=tuple(entries))
    (directory / "active.json").write_text(manifest.model_dump_json())
    return manifest


@patch("smart_factory.infrastructure.ml.registry.IsolationForestAnomalyDetector.load")
def test_loads_and_routes_one_promoted_artifact_per_machine(
    load: Mock,
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    manifest = write_active_manifest(tmp_path, {"press-02": b"two", "press-01": b"one"})
    entries = {entry.machine_id: entry for entry in manifest.entries}
    press_01 = Mock(artifact=Mock(model_id="model-press-01"))
    press_02 = Mock(artifact=Mock(model_id="model-press-02"))
    press_01.evaluate.return_value = ()
    press_02.evaluate.return_value = ()
    load.side_effect = [press_01, press_02]
    resolution = Mock()

    registry = MachineModelRegistry.load(
        tmp_path,
        public_key_path=model_signing_keys[1],
        on_resolution=resolution,
    )
    registry.evaluate(reading("press-02"))

    assert registry.machine_ids == ("press-01", "press-02")
    assert load.call_args_list == [
        call(
            tmp_path / "versions" / "press-01" / f"{entries['press-01'].artifact_sha256}.joblib",
            expected_machine_id="press-01",
            verifier=ANY,
            expected_artifact_sha256=entries["press-01"].artifact_sha256,
        ),
        call(
            tmp_path / "versions" / "press-02" / f"{entries['press-02'].artifact_sha256}.joblib",
            expected_machine_id="press-02",
            verifier=ANY,
            expected_artifact_sha256=entries["press-02"].artifact_sha256,
        ),
    ]
    press_02.evaluate.assert_called_once()
    resolution.assert_called_once_with(True)


def test_uncovered_machine_is_not_scored() -> None:
    detector = Mock()
    resolution = Mock()
    registry = MachineModelRegistry({"press-01": detector}, on_resolution=resolution)

    assert registry.evaluate(reading("press-99")) == ()
    detector.evaluate.assert_not_called()
    resolution.assert_called_once_with(False)


def test_rejects_missing_active_manifest(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    with pytest.raises(MlArtifactError, match="manifest is missing"):
        MachineModelRegistry.load(tmp_path, public_key_path=model_signing_keys[1])


def test_rejects_missing_configured_promoted_model(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    write_active_manifest(tmp_path, {"press-01": b"one"})

    with pytest.raises(MlArtifactError, match="configured machine press-02"):
        MachineModelRegistry.load(
            tmp_path,
            expected_machine_ids=("press-01", "press-02"),
            public_key_path=model_signing_keys[1],
        )


def test_normalizes_invalid_verification_key(tmp_path: Path) -> None:
    write_active_manifest(tmp_path, {"press-01": b"one"})
    public_key_path = tmp_path / "public.pem"
    public_key_path.write_text("not a key")

    with pytest.raises(MlArtifactError, match="could not load ML artifact verification key"):
        MachineModelRegistry.load(tmp_path, public_key_path=public_key_path)


@patch("smart_factory.infrastructure.ml.registry.IsolationForestAnomalyDetector.load")
def test_does_not_activate_unconfigured_manifest_entries(
    load: Mock,
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    manifest = write_active_manifest(tmp_path, {"press-01": b"one", "press-02": b"two"})
    press_01 = next(entry for entry in manifest.entries if entry.machine_id == "press-01")

    load.return_value = Mock(artifact=Mock(model_id="model-press-01"))
    registry = MachineModelRegistry.load(
        tmp_path,
        expected_machine_ids=("press-01",),
        public_key_path=model_signing_keys[1],
    )

    assert registry.machine_ids == ("press-01",)
    load.assert_called_once_with(
        tmp_path / "versions" / "press-01" / f"{press_01.artifact_sha256}.joblib",
        expected_machine_id="press-01",
        verifier=ANY,
        expected_artifact_sha256=press_01.artifact_sha256,
    )


def test_rejects_promoted_artifact_digest_mismatch(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    manifest = write_active_manifest(tmp_path, {"press-01": b"one"})
    entry = manifest.entries[0]
    (tmp_path / "versions" / "press-01" / f"{entry.artifact_sha256}.joblib").write_bytes(
        b"tampered"
    )

    with pytest.raises(MlArtifactError, match="digest"):
        MachineModelRegistry.load(tmp_path, public_key_path=model_signing_keys[1])


@patch("smart_factory.infrastructure.ml.registry.IsolationForestAnomalyDetector.load")
def test_rejects_manifest_model_identity_mismatch(
    load: Mock,
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    write_active_manifest(tmp_path, {"press-01": b"one"})
    load.return_value = Mock(artifact=Mock(model_id="other-model"))

    with pytest.raises(MlArtifactError, match="model identity mismatch"):
        MachineModelRegistry.load(tmp_path, public_key_path=model_signing_keys[1])


def test_publishes_immutable_generation_and_rolls_back_atomically(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    signer = ArtifactSigner.from_private_key_file(model_signing_keys[0])
    verifier = ArtifactVerifier.from_public_key_file(model_signing_keys[1])
    publisher = FilesystemModelRegistryPublisher(tmp_path, verifier)

    candidate_path = tmp_path / "candidates" / "press-01.joblib"
    candidate_path.parent.mkdir()
    candidate_path.write_bytes(b"first")
    artifact_signature_path(candidate_path).write_bytes(signer.sign(b"first"))
    first = publisher.publish(
        (
            PromotionCandidate(
                machine_id="press-01",
                model_id="model-1",
                artifact_sha256=sha256(b"first").hexdigest(),
                artifact_path=candidate_path,
            ),
        )
    )

    candidate_path.write_bytes(b"second")
    artifact_signature_path(candidate_path).write_bytes(signer.sign(b"second"))
    second = publisher.publish(
        (
            PromotionCandidate(
                machine_id="press-01",
                model_id="model-2",
                artifact_sha256=sha256(b"second").hexdigest(),
                artifact_path=candidate_path,
            ),
        )
    )
    rolled_back = publisher.rollback(first.generation_id)

    active = ModelRegistryManifest.model_validate_json((tmp_path / "active.json").read_bytes())
    assert second.previous_generation_id == first.generation_id
    assert rolled_back.source_generation_id == first.generation_id
    assert rolled_back.previous_generation_id == second.generation_id
    assert active == rolled_back
    assert active.entries[0].model_id == "model-1"
    assert (tmp_path / "manifests" / f"{first.generation_id}.json").is_file()
    assert (tmp_path / "manifests" / f"{second.generation_id}.json").is_file()


def test_failed_inference_is_not_counted_as_scored() -> None:
    detector = Mock()
    detector.evaluate.side_effect = RuntimeError("inference failed")
    resolution = Mock()
    registry = MachineModelRegistry({"press-01": detector}, on_resolution=resolution)

    with pytest.raises(RuntimeError, match="inference failed"):
        registry.evaluate(reading("press-01"))

    resolution.assert_not_called()
