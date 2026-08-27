from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from smart_factory.config import MlSettings, OperatorAuditSettings
from smart_factory.rollback_model_main import run


def ml_settings(public_key: str | None = "/keys/public.pem") -> MlSettings:
    return MlSettings(
        enabled=False,
        model_directory="/models",
        machine_ids=("press-01",),
        contamination=0.05,
        minimum_training_samples=100,
        training_limit=10_000,
        signature_public_key_path=public_key,
    )


def runtime_settings() -> Mock:
    return Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )


def audit_settings() -> OperatorAuditSettings:
    return OperatorAuditSettings(
        actor="release-bot",
        reason="ticket-123",
        correlation_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )


@patch("smart_factory.rollback_model_main.ModelRollbackService")
@patch("smart_factory.rollback_model_main.PsycopgOperatorAuditTrail")
@patch("smart_factory.rollback_model_main.FilesystemModelRegistryPublisher")
@patch("smart_factory.rollback_model_main.ArtifactVerifier.from_public_key_file")
def test_rolls_back_to_explicit_generation(
    verifier_from_file: Mock,
    publisher_type: Mock,
    audit_type: Mock,
    service_type: Mock,
) -> None:
    generation_id = UUID("11111111-1111-1111-1111-111111111111")
    service_type.return_value.rollback.return_value = Mock(
        generation_id=UUID("22222222-2222-2222-2222-222222222222"),
        previous_generation_id=UUID("33333333-3333-3333-3333-333333333333"),
        entries=(Mock(machine_id="press-01"),),
    )

    run(runtime_settings(), ml_settings(), audit_settings(), generation_id)

    audit_type.return_value.open.assert_called_once_with(timeout=10)
    audit_type.return_value.close.assert_called_once_with()
    service_type.return_value.rollback.assert_called_once_with(generation_id)
    publisher_type.assert_called_once_with(
        Path("/models"),
        verifier_from_file.return_value,
    )


def test_requires_public_verification_key() -> None:
    with pytest.raises(ValueError, match="ML_SIGNATURE_PUBLIC_KEY_PATH is required"):
        run(
            runtime_settings(),
            ml_settings(None),
            audit_settings(),
            UUID("11111111-1111-1111-1111-111111111111"),
        )
