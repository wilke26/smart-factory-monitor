from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from smart_factory.domain.telemetry import Telemetry


@given(
    temperature=st.floats(min_value=-50, max_value=250, allow_nan=False, allow_infinity=False),
    vibration=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    power=st.floats(min_value=0, max_value=500, allow_nan=False, allow_infinity=False),
    rate=st.integers(min_value=0, max_value=10_000),
)
def test_valid_telemetry_round_trips_through_json(
    temperature: float, vibration: float, power: float, rate: int
) -> None:
    original = Telemetry(
        machine_id="press-01",
        timestamp=datetime(2026, 8, 12, 12, 30, tzinfo=UTC),
        temperature_c=temperature,
        vibration_mm_s=vibration,
        power_kw=power,
        production_rate=rate,
    )

    restored = Telemetry.model_validate_json(original.to_mqtt_payload())

    assert restored == original
