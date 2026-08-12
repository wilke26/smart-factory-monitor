from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from smart_factory.domain.telemetry import Telemetry, TelemetryReading


def valid_telemetry() -> dict[str, object]:
    return {
        "machine_id": "press-01",
        "timestamp": datetime(2026, 8, 12, 12, 30, 15, 123000, tzinfo=UTC),
        "temperature_c": 68.4,
        "vibration_mm_s": 2.7,
        "power_kw": 17.3,
        "production_rate": 44,
    }


def test_serializes_expected_mqtt_payload() -> None:
    telemetry = Telemetry(**valid_telemetry())  # type: ignore[arg-type]

    assert telemetry.to_mqtt_payload() == (
        b'{"machine_id":"press-01","timestamp":"2026-08-12T12:30:15.123000Z",'
        b'"temperature_c":68.4,"vibration_mm_s":2.7,"power_kw":17.3,'
        b'"production_rate":44}'
    )


def test_v01_name_remains_compatible_and_payload_round_trips() -> None:
    telemetry = Telemetry(**valid_telemetry())  # type: ignore[arg-type]

    assert Telemetry is TelemetryReading
    assert TelemetryReading.from_mqtt_payload(telemetry.to_mqtt_payload()) == telemetry


def test_mqtt_payload_rejects_type_coercion() -> None:
    payload = Telemetry(**valid_telemetry()).to_mqtt_payload()  # type: ignore[arg-type]
    invalid = payload.replace(b'"power_kw":17.3', b'"power_kw":"17.3"')

    with pytest.raises(ValidationError):
        TelemetryReading.from_mqtt_payload(invalid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("machine_id", "Press 01"),
        ("timestamp", datetime(2026, 8, 12, 12, 30)),
        ("temperature_c", 251.0),
        ("vibration_mm_s", -0.1),
        ("power_kw", -1.0),
        ("production_rate", -1),
    ],
)
def test_rejects_invalid_contract_values(field: str, value: object) -> None:
    payload = valid_telemetry()
    payload[field] = value

    with pytest.raises(ValidationError):
        Telemetry(**payload)  # type: ignore[arg-type]


def test_rejects_unknown_fields() -> None:
    payload = valid_telemetry()
    payload["unplanned_field"] = "must not cross the boundary"

    with pytest.raises(ValidationError):
        Telemetry(**payload)  # type: ignore[arg-type]
