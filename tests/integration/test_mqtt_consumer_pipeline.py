from types import SimpleNamespace
from unittest.mock import Mock

from smart_factory.application.services.telemetry import TelemetryApplicationService
from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.mqtt.consumer import MqttTelemetryConsumer


def mqtt_message(payload: bytes) -> object:
    return SimpleNamespace(
        payload=payload,
        topic="factory/hall-a/press-01/telemetry",
        mid=7,
        qos=1,
    )


def test_valid_mqtt_message_reaches_application_service(valid_payload: bytes) -> None:
    processed: list[TelemetryReading] = []
    repository = Mock()
    repository.save.return_value = True
    service = TelemetryApplicationService(
        repository=repository, on_processed=processed.append, logger=Mock()
    )
    adapter = MqttTelemetryConsumer(
        "broker", 1883, "consumer", "factory/+/+/telemetry", service, logger=Mock()
    )

    message = mqtt_message(valid_payload)
    client = Mock()
    adapter._on_message(client, None, message)  # type: ignore[arg-type]

    assert len(processed) == 1
    assert processed[0].machine_id == "press-01"
    repository.save.assert_called_once_with(processed[0])
    client.ack.assert_called_once_with(7, 1)


def test_invalid_mqtt_message_is_stopped_at_adapter() -> None:
    processed: list[TelemetryReading] = []
    service = TelemetryApplicationService(
        repository=Mock(), on_processed=processed.append, logger=Mock()
    )
    logger = Mock()
    adapter = MqttTelemetryConsumer(
        "broker", 1883, "consumer", "factory/+/+/telemetry", service, logger=logger
    )

    message = mqtt_message(b'{"machine_id":42}')
    client = Mock()
    adapter._on_message(client, None, message)  # type: ignore[arg-type]

    assert processed == []
    assert service.processed_count == 0
    assert logger.warning.call_args.args[0] == "telemetry_rejected_invalid_payload"
    client.ack.assert_called_once_with(7, 1)
