from types import SimpleNamespace
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt
import pytest

from smart_factory.infrastructure.mqtt.consumer import MqttTelemetryConsumer
from smart_factory.infrastructure.mqtt.publisher import MqttConnectionError


def consumer(*, handler: Mock | None = None, logger: Mock | None = None) -> MqttTelemetryConsumer:
    return MqttTelemetryConsumer(
        "broker",
        1883,
        "consumer",
        "factory/+/+/telemetry",
        handler or Mock(),
        logger=logger or Mock(),
    )


def message(payload: bytes, topic: str = "factory/hall-a/press-01/telemetry") -> object:
    return SimpleNamespace(payload=payload, topic=topic, mid=7, qos=1)


@pytest.mark.parametrize("payload", [b"not-json", b"{}", b'{"machine_id":"press-01"}'])
def test_rejects_invalid_payload_without_calling_handler(payload: bytes) -> None:
    handler = Mock()
    logger = Mock()
    instance = consumer(handler=handler, logger=logger)

    instance._on_message(Mock(), None, message(payload))  # type: ignore[arg-type]

    handler.process.assert_not_called()
    assert logger.warning.call_args.args[0] == "telemetry_rejected_invalid_payload"


def test_rejects_topic_payload_machine_mismatch(valid_payload: bytes) -> None:
    handler = Mock()
    logger = Mock()
    instance = consumer(handler=handler, logger=logger)

    instance._on_message(  # type: ignore[arg-type]
        Mock(), None, message(valid_payload, "factory/hall-a/press-99/telemetry")
    )

    handler.process.assert_not_called()
    assert logger.warning.call_args.args[0] == "telemetry_rejected_topic_mismatch"


def test_rejects_malformed_topic(valid_payload: bytes) -> None:
    handler = Mock()
    logger = Mock()
    instance = consumer(handler=handler, logger=logger)

    instance._on_message(Mock(), None, message(valid_payload, "wrong/topic"))  # type: ignore[arg-type]

    handler.process.assert_not_called()
    assert logger.warning.call_args.args[0] == "telemetry_rejected_invalid_topic"


def test_isolates_application_failure(valid_payload: bytes) -> None:
    handler = Mock()
    handler.process.side_effect = RuntimeError("downstream unavailable")
    logger = Mock()
    instance = consumer(handler=handler, logger=logger)

    mqtt_message = message(valid_payload)
    client = Mock()
    instance._on_message(client, None, mqtt_message)  # type: ignore[arg-type]

    logger.exception.assert_called_once()
    client.ack.assert_not_called()


@patch("smart_factory.infrastructure.mqtt.consumer.mqtt.Client")
def test_connect_timeout_stops_loop(client_factory: Mock) -> None:
    instance = consumer()
    instance._connect_timeout = 0

    with pytest.raises(MqttConnectionError, match="timed out"):
        instance.connect()

    client_factory.return_value.loop_stop.assert_called_once()


@patch("smart_factory.infrastructure.mqtt.consumer.mqtt.Client")
def test_successful_callback_subscribes(client_factory: Mock) -> None:
    client = client_factory.return_value
    client.subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, 7)
    instance = consumer()

    instance._on_connect(client, None, Mock(), Mock(is_failure=False), None)

    assert instance._connected.is_set()
    client.subscribe.assert_called_once_with("factory/+/+/telemetry", qos=1)


@patch("smart_factory.infrastructure.mqtt.consumer.mqtt.Client")
def test_connect_and_subscribe_failures_are_reported(client_factory: Mock) -> None:
    logger = Mock()
    instance = consumer(logger=logger)
    instance._on_connect(client_factory.return_value, None, Mock(), Mock(is_failure=True), None)
    logger.error.assert_called_once()

    logger.reset_mock()
    client_factory.return_value.subscribe.return_value = (mqtt.MQTT_ERR_NO_CONN, 7)
    instance._on_connect(client_factory.return_value, None, Mock(), Mock(is_failure=False), None)
    logger.error.assert_called_once()


def test_disconnect_clears_state_and_logs_failure() -> None:
    logger = Mock()
    instance = consumer(logger=logger)
    instance._connected.set()

    instance._on_disconnect(Mock(), None, Mock(), Mock(is_failure=True), None)

    assert not instance._connected.is_set()
    logger.warning.assert_called_once()
