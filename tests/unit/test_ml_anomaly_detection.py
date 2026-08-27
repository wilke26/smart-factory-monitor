from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import joblib
import pytest

from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactVerifier,
    artifact_sha256,
    artifact_signature_path,
)
from smart_factory.infrastructure.ml.isolation_forest import (
    IsolationForestAnomalyDetector,
    IsolationForestModelEvaluator,
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


def test_trains_loads_and_detects_multivariate_outlier(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
    artifact_verifier: ArtifactVerifier,
) -> None:
    model_path = tmp_path / "isolation-forest.joblib"
    readings = training_readings()

    artifact = IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(
        readings, model_path
    )
    detector = IsolationForestAnomalyDetector.load(
        model_path,
        expected_machine_id="press-01",
        verifier=artifact_verifier,
    )
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
    assert artifact.training_window_end_datetime == readings[-1].timestamp
    assert model_path.exists()
    assert artifact_signature_path(model_path).is_file()
    assert detector.artifact_sha256 == artifact_sha256(model_path)
    assert len(findings) == 1
    assert findings[0].rule_id == "ml-isolation-forest"
    assert findings[0].observed_value < 0
    assert findings[0].threshold == 0


def test_central_training_reading_is_normal(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
    artifact_verifier: ArtifactVerifier,
) -> None:
    readings = training_readings()
    model_path = tmp_path / "model.joblib"
    IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(readings, model_path)
    central = readings[0].model_copy(
        update={
            "temperature_c": 68.2,
            "vibration_mm_s": 2.56,
            "power_kw": 17.1,
            "production_rate": 44,
        }
    )

    assert (
        IsolationForestAnomalyDetector.load(
            model_path,
            expected_machine_id="press-01",
            verifier=artifact_verifier,
        ).evaluate(central)
        == ()
    )


def test_model_does_not_score_a_different_machine(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
    artifact_verifier: ArtifactVerifier,
) -> None:
    readings = training_readings()
    model_path = tmp_path / "model.joblib"
    IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(readings, model_path)
    other_machine = readings[0].model_copy(update={"machine_id": "press-02"})

    assert (
        IsolationForestAnomalyDetector.load(
            model_path,
            expected_machine_id="press-01",
            verifier=artifact_verifier,
        ).evaluate(other_machine)
        == ()
    )


def test_rejects_artifact_for_unconfigured_machine(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
    artifact_verifier: ArtifactVerifier,
) -> None:
    model_path = tmp_path / "model.joblib"
    IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(
        training_readings(), model_path
    )

    with pytest.raises(MlArtifactError, match="expected press-02, got press-01"):
        IsolationForestAnomalyDetector.load(
            model_path,
            expected_machine_id="press-02",
            verifier=artifact_verifier,
        )


def test_rejects_insufficient_training_data(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
) -> None:
    with pytest.raises(ValueError, match="at least 100"):
        IsolationForestTrainer(minimum_samples=100, signer=artifact_signer).train(
            training_readings(99), tmp_path / "model.joblib"
        )


def test_rejects_incompatible_artifact(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
    artifact_verifier: ArtifactVerifier,
) -> None:
    model_path = tmp_path / "model.joblib"
    joblib.dump({"format_version": 999}, model_path)
    artifact_signature_path(model_path).write_bytes(artifact_signer.sign(model_path.read_bytes()))

    with pytest.raises(MlArtifactError, match="unsupported"):
        IsolationForestAnomalyDetector.load(
            model_path,
            expected_machine_id="press-01",
            verifier=artifact_verifier,
        )


def test_missing_artifact_has_dedicated_fail_fast_error(
    tmp_path: Path,
    artifact_verifier: ArtifactVerifier,
) -> None:
    model_path = tmp_path / "missing.joblib"

    with pytest.raises(MlArtifactError, match="could not verify ML artifact") as raised:
        IsolationForestAnomalyDetector.load(
            model_path,
            expected_machine_id="press-01",
            verifier=artifact_verifier,
        )

    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_rejects_tampering_before_joblib_deserialization(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
    artifact_verifier: ArtifactVerifier,
) -> None:
    model_path = tmp_path / "model.joblib"
    IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(
        training_readings(), model_path
    )
    model_path.write_bytes(model_path.read_bytes() + b"tampered")

    with (
        patch("smart_factory.infrastructure.ml.isolation_forest.joblib.load") as load,
        pytest.raises(MlArtifactError, match="signature is invalid"),
    ):
        IsolationForestAnomalyDetector.load(
            model_path,
            expected_machine_id="press-01",
            verifier=artifact_verifier,
        )

    load.assert_not_called()


def test_offline_evaluation_accepts_a_stable_post_training_distribution(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
) -> None:
    readings = training_readings()
    artifact = IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(
        readings,
        tmp_path / "model.joblib",
    )
    evaluation_readings = [
        reading.model_copy(update={"timestamp": reading.timestamp + timedelta(days=1)})
        for reading in readings
    ]

    report = IsolationForestModelEvaluator(
        artifact,
        minimum_samples=100,
        maximum_anomaly_rate=0.1,
        maximum_feature_psi=0.1,
    ).evaluate(evaluation_readings)

    assert report.passed is True
    assert report.failed_gates == ()
    assert report.sample_count == 500
    assert report.anomaly_rate <= 0.1
    assert report.maximum_feature_psi == pytest.approx(0.0)


def test_offline_evaluation_rejects_distribution_drift(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
) -> None:
    readings = training_readings()
    artifact = IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(
        readings,
        tmp_path / "model.joblib",
    )
    shifted = [
        reading.model_copy(
            update={
                "timestamp": reading.timestamp + timedelta(days=1),
                "temperature_c": 120.0,
                "vibration_mm_s": 12.0,
                "power_kw": 45.0,
                "production_rate": 10,
            }
        )
        for reading in readings[:100]
    ]

    report = IsolationForestModelEvaluator(
        artifact,
        minimum_samples=100,
        maximum_anomaly_rate=0.1,
        maximum_feature_psi=0.25,
    ).evaluate(shifted)

    assert report.passed is False
    assert "maximum_anomaly_rate" in report.failed_gates
    assert "maximum_feature_psi" in report.failed_gates


def test_offline_evaluation_rejects_an_insufficient_window(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
) -> None:
    artifact = IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(
        training_readings(),
        tmp_path / "model.joblib",
    )

    report = IsolationForestModelEvaluator(
        artifact,
        minimum_samples=30,
        maximum_anomaly_rate=1.0,
        maximum_feature_psi=10.0,
    ).evaluate(training_readings(29))

    assert report.passed is False
    assert report.failed_gates == ("minimum_samples",)


def test_offline_evaluation_detects_drift_from_a_constant_training_feature(
    tmp_path: Path,
    artifact_signer: ArtifactSigner,
) -> None:
    readings = [
        reading.model_copy(
            update={
                "temperature_c": 68.0,
                "vibration_mm_s": 2.5,
                "power_kw": 17.0,
                "production_rate": 44,
            }
        )
        for reading in training_readings(100)
    ]
    artifact = IsolationForestTrainer(contamination=0.01, signer=artifact_signer).train(
        readings,
        tmp_path / "model.joblib",
    )
    shifted = [
        reading.model_copy(
            update={
                "timestamp": reading.timestamp + timedelta(days=1),
                "temperature_c": 69.0,
            }
        )
        for reading in readings
    ]

    report = IsolationForestModelEvaluator(
        artifact,
        minimum_samples=100,
        maximum_anomaly_rate=1.0,
        maximum_feature_psi=0.25,
    ).evaluate(shifted)

    assert report.passed is False
    assert "maximum_feature_psi" in report.failed_gates
