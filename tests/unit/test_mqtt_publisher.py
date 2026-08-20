from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt
import pytest

from smart_factory.infrastructure.mqtt.publisher import MqttConnectionError, MqttPublisher


@patch("smart_factory.infrastructure.mqtt.publisher.mqtt.Client")
def test_connect_times_out_and_closes_client(client_factory: Mock) -> None:
    client = client_factory.return_value
    publisher = MqttPublisher("broker", 1883, "test-client", connect_timeout=0)

    with pytest.raises(MqttConnectionError, match="timed out"):
        publisher.connect()

    client.connect.assert_called_once_with("broker", 1883, 60)
    client.loop_start.assert_called_once()
    client.loop_stop.assert_called_once()


@patch("smart_factory.infrastructure.mqtt.publisher.mqtt.Client")
def test_publish_requires_connection(client_factory: Mock) -> None:
    publisher = MqttPublisher("broker", 1883, "test-client")

    with pytest.raises(MqttConnectionError, match="not connected"):
        publisher.publish("factory/hall-a/press-01/telemetry", b"{}")


@patch("smart_factory.infrastructure.mqtt.publisher.mqtt.Client")
def test_publish_waits_for_successful_handoff(client_factory: Mock) -> None:
    client = client_factory.return_value
    result = client.publish.return_value
    result.rc = mqtt.MQTT_ERR_SUCCESS
    result.is_published.return_value = True
    publisher = MqttPublisher("broker", 1883, "test-client")
    publisher._connected.set()

    publisher.publish("factory/hall-a/press-01/telemetry", b"{}", qos=1)

    client.publish.assert_called_once_with(
        "factory/hall-a/press-01/telemetry", payload=b"{}", qos=1, retain=False
    )
    result.wait_for_publish.assert_called_once_with(timeout=10.0)
    result.is_published.assert_called_once_with()


@patch("smart_factory.infrastructure.mqtt.publisher.mqtt.Client")
def test_publish_reports_acknowledgement_timeout(client_factory: Mock) -> None:
    result = client_factory.return_value.publish.return_value
    result.rc = mqtt.MQTT_ERR_SUCCESS
    result.is_published.return_value = False
    publisher = MqttPublisher("broker", 1883, "test-client")
    publisher._connected.set()

    with pytest.raises(MqttConnectionError, match="acknowledgement timed out"):
        publisher.publish("factory/hall-a/press-01/telemetry", b"{}")


@patch("smart_factory.infrastructure.mqtt.publisher.mqtt.Client")
def test_publish_reports_client_failure(client_factory: Mock) -> None:
    result = client_factory.return_value.publish.return_value
    result.rc = mqtt.MQTT_ERR_NO_CONN
    publisher = MqttPublisher("broker", 1883, "test-client")
    publisher._connected.set()

    with pytest.raises(MqttConnectionError, match="result code"):
        publisher.publish("factory/hall-a/press-01/telemetry", b"{}")


@patch("smart_factory.infrastructure.mqtt.publisher.mqtt.Client")
def test_close_disconnects_active_client(client_factory: Mock) -> None:
    client = client_factory.return_value
    publisher = MqttPublisher("broker", 1883, "test-client")
    publisher._connected.set()

    publisher.close()

    client.disconnect.assert_called_once()
    client.loop_stop.assert_called_once()


@patch("smart_factory.infrastructure.mqtt.publisher.mqtt.Client")
def test_successful_connect_callback_marks_publisher_connected(client_factory: Mock) -> None:
    publisher = MqttPublisher("broker", 1883, "test-client")
    reason_code = Mock(is_failure=False)

    publisher._on_connect(client_factory.return_value, None, Mock(), reason_code, None)

    assert publisher._connected.is_set()


@patch("smart_factory.infrastructure.mqtt.publisher.mqtt.Client")
def test_failed_disconnect_callback_clears_connection(client_factory: Mock) -> None:
    publisher = MqttPublisher("broker", 1883, "test-client")
    publisher._connected.set()
    reason_code = Mock(is_failure=True)

    publisher._on_disconnect(client_factory.return_value, None, Mock(), reason_code, None)

    assert not publisher._connected.is_set()
