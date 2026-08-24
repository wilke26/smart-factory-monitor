from datetime import UTC, datetime
from pathlib import Path

import pytest

from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactVerifier,
    ensure_ed25519_key_pair,
)


@pytest.fixture
def model_signing_keys(tmp_path: Path) -> tuple[Path, Path]:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    ensure_ed25519_key_pair(private_path, public_path)
    return private_path, public_path


@pytest.fixture
def artifact_signer(model_signing_keys: tuple[Path, Path]) -> ArtifactSigner:
    return ArtifactSigner.from_private_key_file(model_signing_keys[0])


@pytest.fixture
def artifact_verifier(model_signing_keys: tuple[Path, Path]) -> ArtifactVerifier:
    return ArtifactVerifier.from_public_key_file(model_signing_keys[1])


@pytest.fixture
def valid_payload() -> bytes:
    return TelemetryReading(
        machine_id="press-01",
        timestamp=datetime(2026, 8, 12, 12, 30, tzinfo=UTC),
        temperature_c=68.4,
        vibration_mm_s=2.7,
        power_kw=17.3,
        production_rate=44,
    ).to_mqtt_payload()
