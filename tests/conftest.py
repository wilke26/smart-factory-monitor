from datetime import UTC, datetime

import pytest

from smart_factory.domain.telemetry import TelemetryReading


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
