from smart_factory.domain.telemetry import Telemetry
from smart_factory.simulator.machine import MachineSimulator


def test_simulator_output_can_be_consumed_via_public_contract() -> None:
    measurement = MachineSimulator(seed=123).next_measurement()

    consumed = Telemetry.model_validate_json(measurement.to_mqtt_payload())

    assert consumed == measurement
