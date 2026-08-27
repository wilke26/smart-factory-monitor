"""Console entry point for explicit rollback to a registry generation."""

import logging
import os
from pathlib import Path
from uuid import UUID

from smart_factory.application.services.model_promotion import ModelRollbackService
from smart_factory.config import MlSettings, OperatorAuditSettings, Settings
from smart_factory.infrastructure.database.operator_audit import PsycopgOperatorAuditTrail
from smart_factory.infrastructure.ml.artifact_signing import ArtifactVerifier
from smart_factory.infrastructure.ml.registry import FilesystemModelRegistryPublisher
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(
    settings: Settings,
    ml_settings: MlSettings,
    audit_settings: OperatorAuditSettings,
    generation_id: UUID,
) -> None:
    if ml_settings.signature_public_key_path is None:
        raise ValueError("ML_SIGNATURE_PUBLIC_KEY_PATH is required for model rollback")
    verifier = ArtifactVerifier.from_public_key_file(Path(ml_settings.signature_public_key_path))
    registry = FilesystemModelRegistryPublisher(
        Path(ml_settings.model_directory),
        verifier,
    )
    audit_trail = PsycopgOperatorAuditTrail(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    try:
        audit_trail.open(timeout=settings.database_connect_timeout_seconds)
        manifest = ModelRollbackService(
            registry,
            audit_trail,
            audit_settings.context,
        ).rollback(generation_id)
    finally:
        audit_trail.close()
    LOGGER.info(
        "ml_models_rolled_back",
        extra={
            "generation_id": str(manifest.generation_id),
            "source_generation_id": str(generation_id),
            "previous_generation_id": str(manifest.previous_generation_id),
            "machine_ids": [entry.machine_id for entry in manifest.entries],
            "actor": audit_settings.actor,
            "correlation_id": str(audit_settings.correlation_id),
        },
    )


def main() -> None:
    settings = Settings.from_env()
    ml_settings = MlSettings.from_env()
    audit_settings = OperatorAuditSettings.from_env()
    configure_logging(settings.log_level)
    raw_generation_id = os.getenv("ML_ROLLBACK_GENERATION_ID", "").strip()
    if not raw_generation_id:
        raise ValueError("ML_ROLLBACK_GENERATION_ID is required for model rollback")
    try:
        generation_id = UUID(raw_generation_id)
    except ValueError as error:
        raise ValueError("ML_ROLLBACK_GENERATION_ID must be a UUID") from error
    run(settings, ml_settings, audit_settings, generation_id)


if __name__ == "__main__":
    main()
