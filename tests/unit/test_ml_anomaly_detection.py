from datetime import UTC, datetime, timedelta
from pathlib import Path

import joblib
import pytest

from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.ml.isolation_forest import (
    IsolationForestAnomalyDetector,
    IsolationForestTrainer,
    MlArtifactError,
)
from smart_factory.simulator.machine import MachineSimulator


def training_readings(count: int = 500) -> list[TelemetryReading]:
    start = datetime(2026, 8, 13, tzinfo=UTC)
    simulator = MachineSimulator("press-01", seed=42, clock=lambda: start)
    return [
        simulator.next_measurement().model_copy(
            update={"timestamp": start + timedelta(seconds=index)}
        )
        for index in range(count)
    ]


def test_trains_loads_and_detects_multivariate_outlier(tmp_path: Path) -> None:
    model_path = tmp_path / "isolation-forest.joblib"
    readings = training_readings()

    artifact = IsolationForestTrainer(contamination=0.01).train(readings, model_path)
    detector = IsolationForestAnomalyDetector.load(model_path)
    outlier = readings[0].model_copy(
        update={
            "timestamp": datetime(2026, 8, 14, tzinfo=UTC),
            "temperature_c": 88.0,
            "vibration_mm_s": 6.5,
            "power_kw": 29.0,
            "production_rate": 27,
        }
    )

    findings = detector.evaluate(outlier)

    assert artifact.training_samples == 500
    assert artifact.machine_id == "press-01"
    assert model_path.exists()
    assert len(findings) == 1
    assert findings[0].rule_id == "ml-isolation-forest"
    assert findings[0].observed_value < 0
    assert findings[0].threshold == 0


def test_central_training_reading_is_normal(tmp_path: Path) -> None:
    readings = training_readings()
    model_path = tmp_path / "model.joblib"
    IsolationForestTrainer(contamination=0.01).train(readings, model_path)
    central = readings[0].model_copy(
        update={
            "temperature_c": 68.2,
            "vibration_mm_s": 2.56,
            "power_kw": 17.1,
            "production_rate": 44,
        }
    )

    assert IsolationForestAnomalyDetector.load(model_path).evaluate(central) == ()


def test_model_does_not_score_a_different_machine(tmp_path: Path) -> None:
    readings = training_readings()
    model_path = tmp_path / "model.joblib"
    IsolationForestTrainer(contamination=0.01).train(readings, model_path)
    other_machine = readings[0].model_copy(update={"machine_id": "press-02"})

    assert IsolationForestAnomalyDetector.load(model_path).evaluate(other_machine) == ()


def test_rejects_insufficient_training_data(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 100"):
        IsolationForestTrainer(minimum_samples=100).train(
            training_readings(99), tmp_path / "model.joblib"
        )


def test_rejects_incompatible_artifact(tmp_path: Path) -> None:
    model_path = tmp_path / "model.joblib"
    joblib.dump({"format_version": 999}, model_path)

    with pytest.raises(MlArtifactError, match="unsupported"):
        IsolationForestAnomalyDetector.load(model_path)


def test_missing_artifact_has_dedicated_fail_fast_error(tmp_path: Path) -> None:
    model_path = tmp_path / "missing.joblib"

    with pytest.raises(MlArtifactError, match="could not load ML artifact") as raised:
        IsolationForestAnomalyDetector.load(model_path)

    assert isinstance(raised.value.__cause__, FileNotFoundError)
