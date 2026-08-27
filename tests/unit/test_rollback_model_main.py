from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from smart_factory.config import MlSettings
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


@patch("smart_factory.rollback_model_main.FilesystemModelRegistryPublisher")
@patch("smart_factory.rollback_model_main.ArtifactVerifier.from_public_key_file")
def test_rolls_back_to_explicit_generation(
    verifier_from_file: Mock,
    publisher_type: Mock,
) -> None:
    generation_id = UUID("11111111-1111-1111-1111-111111111111")
    publisher_type.return_value.rollback.return_value = Mock(
        generation_id=UUID("22222222-2222-2222-2222-222222222222"),
        previous_generation_id=UUID("33333333-3333-3333-3333-333333333333"),
        entries=(Mock(machine_id="press-01"),),
    )

    run(ml_settings(), generation_id)

    publisher_type.return_value.rollback.assert_called_once_with(generation_id)


def test_requires_public_verification_key() -> None:
    with pytest.raises(ValueError, match="ML_SIGNATURE_PUBLIC_KEY_PATH is required"):
        run(ml_settings(None), UUID("11111111-1111-1111-1111-111111111111"))
