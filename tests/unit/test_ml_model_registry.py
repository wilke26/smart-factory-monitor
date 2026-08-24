from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import ANY, Mock, call, patch

import pytest

from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.ml.isolation_forest import MlArtifactError
from smart_factory.infrastructure.ml.registry import MachineModelRegistry


def reading(machine_id: str) -> TelemetryReading:
    return TelemetryReading(
        machine_id=machine_id,
        timestamp=datetime(2026, 8, 24, tzinfo=UTC),
        temperature_c=68.0,
        vibration_mm_s=2.5,
        power_kw=17.0,
        production_rate=44,
    )


@patch("smart_factory.infrastructure.ml.registry.IsolationForestAnomalyDetector.load")
def test_loads_and_routes_one_artifact_per_machine(
    load: Mock,
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    for machine_id in ("press-02", "press-01"):
        (tmp_path / f"{machine_id}.joblib").touch()
    press_01 = Mock()
    press_02 = Mock()
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
        call(tmp_path / "press-01.joblib", expected_machine_id="press-01", verifier=ANY),
        call(tmp_path / "press-02.joblib", expected_machine_id="press-02", verifier=ANY),
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


def test_rejects_empty_model_directory(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    with pytest.raises(MlArtifactError, match="no ML artifacts"):
        MachineModelRegistry.load(tmp_path, public_key_path=model_signing_keys[1])


def test_rejects_missing_configured_machine_artifact(
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    (tmp_path / "press-01.joblib").touch()

    with pytest.raises(MlArtifactError, match="configured machine press-02"):
        MachineModelRegistry.load(
            tmp_path,
            expected_machine_ids=("press-01", "press-02"),
            public_key_path=model_signing_keys[1],
        )


def test_normalizes_invalid_verification_key(
    tmp_path: Path,
) -> None:
    (tmp_path / "press-01.joblib").touch()
    public_key_path = tmp_path / "public.pem"
    public_key_path.write_text("not a key")

    with pytest.raises(MlArtifactError, match="could not load ML artifact verification key"):
        MachineModelRegistry.load(tmp_path, public_key_path=public_key_path)


@patch("smart_factory.infrastructure.ml.registry.IsolationForestAnomalyDetector.load")
def test_does_not_activate_unconfigured_artifacts(
    load: Mock,
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    (tmp_path / "press-01.joblib").touch()
    (tmp_path / "stale-machine.joblib").touch()

    registry = MachineModelRegistry.load(
        tmp_path,
        expected_machine_ids=("press-01",),
        public_key_path=model_signing_keys[1],
    )

    assert registry.machine_ids == ("press-01",)
    load.assert_called_once_with(
        tmp_path / "press-01.joblib",
        expected_machine_id="press-01",
        verifier=ANY,
    )


def test_failed_inference_is_not_counted_as_scored() -> None:
    detector = Mock()
    detector.evaluate.side_effect = RuntimeError("inference failed")
    resolution = Mock()
    registry = MachineModelRegistry({"press-01": detector}, on_resolution=resolution)

    with pytest.raises(RuntimeError, match="inference failed"):
        registry.evaluate(reading("press-01"))

    resolution.assert_not_called()
