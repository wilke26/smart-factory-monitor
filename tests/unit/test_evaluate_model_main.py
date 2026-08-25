from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from smart_factory.config import MlSettings
from smart_factory.evaluate_model_main import run
from smart_factory.infrastructure.ml.isolation_forest import ModelEvaluationError


def ml_settings() -> MlSettings:
    return MlSettings(
        enabled=False,
        model_directory="/models",
        machine_ids=("press-01", "press-02"),
        contamination=0.05,
        minimum_training_samples=100,
        training_limit=10_000,
        signature_public_key_path="/keys/public.pem",
        evaluation_minimum_samples=30,
        evaluation_limit=500,
        maximum_evaluation_anomaly_rate=0.1,
        maximum_feature_psi=0.2,
    )


def runtime_settings() -> Mock:
    return Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )


@patch("smart_factory.evaluate_model_main.IsolationForestModelEvaluator")
@patch("smart_factory.evaluate_model_main.IsolationForestAnomalyDetector.load")
@patch("smart_factory.evaluate_model_main.PsycopgTelemetryRepository")
@patch("smart_factory.evaluate_model_main.ArtifactVerifier.from_public_key_file")
def test_evaluates_each_machine_from_post_training_history(
    verifier_from_file: Mock,
    repository_type: Mock,
    detector_load: Mock,
    evaluator_type: Mock,
) -> None:
    training_window_end = datetime(2026, 8, 25, tzinfo=UTC)
    artifacts = [
        Mock(
            model_id="model-1",
            machine_id="press-01",
            training_window_end_datetime=training_window_end,
        ),
        Mock(
            model_id="model-2",
            machine_id="press-02",
            training_window_end_datetime=training_window_end,
        ),
    ]
    detector_load.side_effect = [Mock(artifact=artifact) for artifact in artifacts]
    repository_type.return_value.load_readings_since.side_effect = [[Mock()], [Mock()]]
    evaluator_type.return_value.evaluate.side_effect = [
        Mock(
            model_id="model-1",
            machine_id="press-01",
            sample_count=50,
            anomaly_rate=0.02,
            feature_psi=(("temperature_c", 0.01),),
            maximum_feature_psi=0.01,
            passed=True,
            failed_gates=(),
        ),
        Mock(
            model_id="model-2",
            machine_id="press-02",
            sample_count=50,
            anomaly_rate=0.03,
            feature_psi=(("temperature_c", 0.02),),
            maximum_feature_psi=0.02,
            passed=True,
            failed_gates=(),
        ),
    ]

    run(runtime_settings(), ml_settings())

    verifier_from_file.assert_called_once_with(Path("/keys/public.pem"))
    assert detector_load.call_args_list == [
        call(
            Path("/models/press-01.joblib"),
            expected_machine_id="press-01",
            verifier=verifier_from_file.return_value,
        ),
        call(
            Path("/models/press-02.joblib"),
            expected_machine_id="press-02",
            verifier=verifier_from_file.return_value,
        ),
    ]
    assert repository_type.return_value.load_readings_since.call_args_list == [
        call("press-01", training_window_end, 500),
        call("press-02", training_window_end, 500),
    ]
    repository_type.return_value.close.assert_called_once()


@patch("smart_factory.evaluate_model_main.IsolationForestModelEvaluator")
@patch("smart_factory.evaluate_model_main.IsolationForestAnomalyDetector.load")
@patch("smart_factory.evaluate_model_main.PsycopgTelemetryRepository")
@patch("smart_factory.evaluate_model_main.ArtifactVerifier.from_public_key_file")
def test_reports_all_evaluation_gate_failures_after_closing_repository(
    verifier_from_file: Mock,
    repository_type: Mock,
    detector_load: Mock,
    evaluator_type: Mock,
) -> None:
    artifact = Mock(training_window_end_datetime=datetime(2026, 8, 25, tzinfo=UTC))
    detector_load.return_value = Mock(artifact=artifact)
    evaluator_type.return_value.evaluate.return_value = Mock(
        model_id="model",
        machine_id="press-01",
        sample_count=0,
        anomaly_rate=0.0,
        feature_psi=(),
        maximum_feature_psi=0.0,
        passed=False,
        failed_gates=("minimum_samples",),
    )

    with pytest.raises(ModelEvaluationError, match="press-01, press-02"):
        run(runtime_settings(), ml_settings())

    repository_type.return_value.close.assert_called_once()


def test_requires_public_verification_key_before_database_access() -> None:
    settings = ml_settings()
    settings = MlSettings(
        enabled=settings.enabled,
        model_directory=settings.model_directory,
        machine_ids=settings.machine_ids,
        contamination=settings.contamination,
        minimum_training_samples=settings.minimum_training_samples,
        training_limit=settings.training_limit,
    )

    with pytest.raises(ValueError, match="ML_SIGNATURE_PUBLIC_KEY_PATH is required"):
        run(runtime_settings(), settings)
