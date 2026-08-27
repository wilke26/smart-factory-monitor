"""Console entry point for explicit offline model training."""

import logging
from pathlib import Path

from smart_factory.config import MlSettings, Settings
from smart_factory.infrastructure.database.telemetry_repository import PsycopgTelemetryRepository
from smart_factory.infrastructure.ml.artifact_signing import ArtifactSigner
from smart_factory.infrastructure.ml.isolation_forest import IsolationForestTrainer
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(settings: Settings, ml_settings: MlSettings) -> None:
    if ml_settings.signing_private_key_path is None:
        raise ValueError("ML_SIGNING_PRIVATE_KEY_PATH is required for model training")
    signer = ArtifactSigner.from_private_key_file(Path(ml_settings.signing_private_key_path))
    repository = PsycopgTelemetryRepository(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    try:
        repository.open(timeout=settings.database_connect_timeout_seconds)
        training_sets = {
            machine_id: repository.load_recent_readings(
                machine_id,
                ml_settings.training_limit,
            )
            for machine_id in ml_settings.machine_ids
        }
        insufficient = [
            machine_id
            for machine_id, readings in training_sets.items()
            if len(readings) < ml_settings.minimum_training_samples
        ]
        if insufficient:
            machine_id = insufficient[0]
            raise ValueError(
                f"at least {ml_settings.minimum_training_samples} readings are required "
                f"for {machine_id}; got {len(training_sets[machine_id])}"
            )
        trainer = IsolationForestTrainer(
            contamination=ml_settings.contamination,
            minimum_samples=ml_settings.minimum_training_samples,
            signer=signer,
        )
        for machine_id, readings in training_sets.items():
            model_path = Path(ml_settings.model_directory) / "candidates" / f"{machine_id}.joblib"
            artifact = trainer.train(readings, model_path)
            LOGGER.info(
                "ml_model_trained",
                extra={
                    "model_id": artifact.model_id,
                    "machine_id": artifact.machine_id,
                    "training_samples": artifact.training_samples,
                    "model_path": str(model_path),
                },
            )
    finally:
        repository.close()


def main() -> None:
    settings = Settings.from_env()
    ml_settings = MlSettings.from_env()
    configure_logging(settings.log_level)
    run(settings, ml_settings)


if __name__ == "__main__":
    main()
