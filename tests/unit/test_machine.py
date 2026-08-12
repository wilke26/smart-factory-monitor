from datetime import UTC, datetime

from smart_factory.simulator.machine import MachineSimulator

FIXED_TIME = datetime(2026, 8, 12, 12, 30, tzinfo=UTC)


def test_generates_plausible_press_measurement() -> None:
    simulator = MachineSimulator("press-01", seed=42, clock=lambda: FIXED_TIME)

    measurement = simulator.next_measurement()

    assert measurement.machine_id == "press-01"
    assert measurement.timestamp == FIXED_TIME
    assert 55.0 <= measurement.temperature_c <= 75.0
    assert 1.0 <= measurement.vibration_mm_s <= 4.0
    assert 12.0 <= measurement.power_kw <= 22.0
    assert 35 <= measurement.production_rate <= 50


def test_seed_makes_simulation_repeatable() -> None:
    first = MachineSimulator("press-01", seed=7, clock=lambda: FIXED_TIME)
    second = MachineSimulator("press-01", seed=7, clock=lambda: FIXED_TIME)

    assert first.next_measurement() == second.next_measurement()
