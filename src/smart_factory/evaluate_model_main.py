"""Console entry point for signed, post-training model evaluation."""

import logging
from pathlib import Path

from smart_factory.config import MlSettings, Settings
from smart_factory.infrastructure.database.telemetry_repository import PsycopgTelemetryRepository
from smart_factory.infrastructure.ml.artifact_signing import ArtifactVerifier
from smart_factory.infrastructure.ml.isolation_forest import (
    IsolationForestAnomalyDetector,
    IsolationForestModelEvaluator,
    ModelEvaluationError,
)
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(settings: Settings, ml_settings: MlSettings) -> None:
    if ml_settings.signature_public_key_path is None:
        raise ValueError("ML_SIGNATURE_PUBLIC_KEY_PATH is required for model evaluation")
    verifier = ArtifactVerifier.from_public_key_file(Path(ml_settings.signature_public_key_path))
    repository = PsycopgTelemetryRepository(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    failed_machines: list[str] = []
    try:
        repository.open(timeout=settings.database_connect_timeout_seconds)
        for machine_id in ml_settings.machine_ids:
            detector = IsolationForestAnomalyDetector.load(
                Path(ml_settings.model_directory) / f"{machine_id}.joblib",
                expected_machine_id=machine_id,
                verifier=verifier,
            )
            artifact = detector.artifact
            readings = repository.load_readings_since(
                machine_id,
                artifact.training_window_end_datetime,
                ml_settings.evaluation_limit,
            )
            report = IsolationForestModelEvaluator(
                artifact,
                minimum_samples=ml_settings.evaluation_minimum_samples,
                maximum_anomaly_rate=ml_settings.maximum_evaluation_anomaly_rate,
                maximum_feature_psi=ml_settings.maximum_feature_psi,
            ).evaluate(readings)
            LOGGER.info(
                "ml_model_evaluated",
                extra={
                    "model_id": report.model_id,
                    "machine_id": report.machine_id,
                    "evaluation_samples": report.sample_count,
                    "anomaly_rate": report.anomaly_rate,
                    "feature_psi": dict(report.feature_psi),
                    "maximum_feature_psi": report.maximum_feature_psi,
                    "evaluation_passed": report.passed,
                    "failed_gates": report.failed_gates,
                },
            )
            if not report.passed:
                failed_machines.append(machine_id)
    finally:
        repository.close()
    if failed_machines:
        raise ModelEvaluationError("ML evaluation gates failed for: " + ", ".join(failed_machines))


def main() -> None:
    settings = Settings.from_env()
    ml_settings = MlSettings.from_env()
    configure_logging(settings.log_level)
    run(settings, ml_settings)


if __name__ == "__main__":
    main()
