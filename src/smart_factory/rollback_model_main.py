"""Console entry point for explicit rollback to a registry generation."""

import logging
import os
from pathlib import Path
from uuid import UUID

from smart_factory.config import MlSettings, Settings
from smart_factory.infrastructure.ml.artifact_signing import ArtifactVerifier
from smart_factory.infrastructure.ml.registry import FilesystemModelRegistryPublisher
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(ml_settings: MlSettings, generation_id: UUID) -> None:
    if ml_settings.signature_public_key_path is None:
        raise ValueError("ML_SIGNATURE_PUBLIC_KEY_PATH is required for model rollback")
    verifier = ArtifactVerifier.from_public_key_file(Path(ml_settings.signature_public_key_path))
    manifest = FilesystemModelRegistryPublisher(
        Path(ml_settings.model_directory),
        verifier,
    ).rollback(generation_id)
    LOGGER.info(
        "ml_models_rolled_back",
        extra={
            "generation_id": str(manifest.generation_id),
            "source_generation_id": str(generation_id),
            "previous_generation_id": str(manifest.previous_generation_id),
            "machine_ids": [entry.machine_id for entry in manifest.entries],
        },
    )


def main() -> None:
    settings = Settings.from_env()
    ml_settings = MlSettings.from_env()
    configure_logging(settings.log_level)
    raw_generation_id = os.getenv("ML_ROLLBACK_GENERATION_ID", "").strip()
    if not raw_generation_id:
        raise ValueError("ML_ROLLBACK_GENERATION_ID is required for model rollback")
    try:
        generation_id = UUID(raw_generation_id)
    except ValueError as error:
        raise ValueError("ML_ROLLBACK_GENERATION_ID must be a UUID") from error
    run(ml_settings, generation_id)


if __name__ == "__main__":
    main()
