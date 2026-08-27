from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from smart_factory.config import MlSettings
from smart_factory.promote_model_main import run


def ml_settings() -> MlSettings:
    return MlSettings(
        enabled=False,
        model_directory="/models",
        machine_ids=("press-01", "press-02"),
        contamination=0.05,
        minimum_training_samples=100,
        training_limit=10_000,
        signature_public_key_path="/keys/public.pem",
    )


def runtime_settings() -> Mock:
    return Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )


@patch("smart_factory.promote_model_main.ModelPromotionService")
@patch("smart_factory.promote_model_main.FilesystemModelRegistryPublisher")
@patch("smart_factory.promote_model_main.PsycopgModelEvaluationStore")
@patch("smart_factory.promote_model_main.IsolationForestAnomalyDetector.load")
@patch("smart_factory.promote_model_main.ArtifactVerifier.from_public_key_file")
def test_promotes_verified_candidates_and_closes_store(
    verifier_from_file: Mock,
    detector_load: Mock,
    store_type: Mock,
    publisher_type: Mock,
    service_type: Mock,
) -> None:
    detector_load.side_effect = [
        Mock(artifact=Mock(model_id="model-1"), artifact_sha256="a" * 64),
        Mock(artifact=Mock(model_id="model-2"), artifact_sha256="b" * 64),
    ]
    service_type.return_value.promote.return_value = Mock(
        generation_id="generation",
        previous_generation_id=None,
        entries=(Mock(machine_id="press-01"), Mock(machine_id="press-02")),
    )

    run(runtime_settings(), ml_settings())

    assert detector_load.call_args_list == [
        call(
            Path("/models/candidates/press-01.joblib"),
            expected_machine_id="press-01",
            verifier=verifier_from_file.return_value,
        ),
        call(
            Path("/models/candidates/press-02.joblib"),
            expected_machine_id="press-02",
            verifier=verifier_from_file.return_value,
        ),
    ]
    store_type.return_value.open.assert_called_once_with(timeout=10)
    store_type.return_value.close.assert_called_once()
    publisher_type.assert_called_once_with(Path("/models"), verifier_from_file.return_value)
    promoted = service_type.return_value.promote.call_args.args[0]
    assert [(item.machine_id, item.model_id, item.artifact_sha256) for item in promoted] == [
        ("press-01", "model-1", "a" * 64),
        ("press-02", "model-2", "b" * 64),
    ]


@patch("smart_factory.promote_model_main.ModelPromotionService")
@patch("smart_factory.promote_model_main.FilesystemModelRegistryPublisher")
@patch("smart_factory.promote_model_main.PsycopgModelEvaluationStore")
@patch("smart_factory.promote_model_main.IsolationForestAnomalyDetector.load")
@patch("smart_factory.promote_model_main.ArtifactVerifier.from_public_key_file")
def test_closes_store_when_promotion_fails(
    verifier_from_file: Mock,
    detector_load: Mock,
    store_type: Mock,
    publisher_type: Mock,
    service_type: Mock,
) -> None:
    del verifier_from_file, publisher_type
    detector_load.return_value = Mock(artifact=Mock(model_id="model"), artifact_sha256="a" * 64)
    service_type.return_value.promote.side_effect = RuntimeError("not approved")

    with pytest.raises(RuntimeError, match="not approved"):
        run(runtime_settings(), ml_settings())

    store_type.return_value.close.assert_called_once()


def test_requires_public_verification_key_before_candidate_access() -> None:
    settings = ml_settings()
    settings = MlSettings(
        enabled=False,
        model_directory=settings.model_directory,
        machine_ids=settings.machine_ids,
        contamination=settings.contamination,
        minimum_training_samples=settings.minimum_training_samples,
        training_limit=settings.training_limit,
    )

    with pytest.raises(ValueError, match="ML_SIGNATURE_PUBLIC_KEY_PATH is required"):
        run(runtime_settings(), settings)
