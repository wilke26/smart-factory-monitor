"""Console entry point for evaluation-gated atomic model promotion."""

import logging
from pathlib import Path

from smart_factory.application.services.model_promotion import (
    ModelPromotionService,
    PromotionCandidate,
)
from smart_factory.config import MlSettings, OperatorAuditSettings, Settings
from smart_factory.infrastructure.database.model_evaluation_store import (
    PsycopgModelEvaluationStore,
)
from smart_factory.infrastructure.database.operator_audit import PsycopgOperatorAuditTrail
from smart_factory.infrastructure.ml.artifact_signing import ArtifactVerifier
from smart_factory.infrastructure.ml.isolation_forest import IsolationForestAnomalyDetector
from smart_factory.infrastructure.ml.registry import FilesystemModelRegistryPublisher
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(
    settings: Settings,
    ml_settings: MlSettings,
    audit_settings: OperatorAuditSettings,
) -> None:
    if ml_settings.signature_public_key_path is None:
        raise ValueError("ML_SIGNATURE_PUBLIC_KEY_PATH is required for model promotion")
    verifier = ArtifactVerifier.from_public_key_file(Path(ml_settings.signature_public_key_path))
    directory = Path(ml_settings.model_directory)
    candidates: list[PromotionCandidate] = []
    for machine_id in ml_settings.machine_ids:
        artifact_path = directory / "candidates" / f"{machine_id}.joblib"
        detector = IsolationForestAnomalyDetector.load(
            artifact_path,
            expected_machine_id=machine_id,
            verifier=verifier,
        )
        candidates.append(
            PromotionCandidate(
                machine_id=machine_id,
                model_id=detector.artifact.model_id,
                artifact_sha256=detector.artifact_sha256,
                artifact_path=artifact_path,
            )
        )
    store = PsycopgModelEvaluationStore(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    audit_trail = PsycopgOperatorAuditTrail(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    try:
        store.open(timeout=settings.database_connect_timeout_seconds)
        audit_trail.open(timeout=settings.database_connect_timeout_seconds)
        manifest = ModelPromotionService(
            store,
            FilesystemModelRegistryPublisher(directory, verifier),
            audit_trail,
            audit_settings.context,
        ).promote(tuple(candidates))
    finally:
        audit_trail.close()
        store.close()
    LOGGER.info(
        "ml_models_promoted",
        extra={
            "generation_id": str(manifest.generation_id),
            "previous_generation_id": (
                str(manifest.previous_generation_id)
                if manifest.previous_generation_id is not None
                else None
            ),
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
    run(settings, ml_settings, audit_settings)


if __name__ == "__main__":
    main()
