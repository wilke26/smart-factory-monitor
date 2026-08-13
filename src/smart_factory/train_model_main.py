"""Console entry point for explicit offline model training."""

import logging
from pathlib import Path

from smart_factory.config import MlSettings, Settings
from smart_factory.infrastructure.database.telemetry_repository import PsycopgTelemetryRepository
from smart_factory.infrastructure.ml.isolation_forest import IsolationForestTrainer
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(settings: Settings, ml_settings: MlSettings) -> None:
    repository = PsycopgTelemetryRepository(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    try:
        repository.open(timeout=settings.database_connect_timeout_seconds)
        readings = repository.load_recent_readings(
            ml_settings.machine_id, ml_settings.training_limit
        )
        artifact = IsolationForestTrainer(
            contamination=ml_settings.contamination,
            minimum_samples=ml_settings.minimum_training_samples,
        ).train(readings, Path(ml_settings.model_path))
    finally:
        repository.close()
    LOGGER.info(
        "ml_model_trained",
        extra={
            "model_id": artifact.model_id,
            "machine_id": artifact.machine_id,
            "training_samples": artifact.training_samples,
            "model_path": ml_settings.model_path,
        },
    )


def main() -> None:
    settings = Settings.from_env()
    ml_settings = MlSettings.from_env()
    configure_logging(settings.log_level)
    run(settings, ml_settings)


if __name__ == "__main__":
    main()
