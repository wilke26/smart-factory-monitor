"""MQTT 5 publisher adapter."""

import logging
import threading
from types import TracebackType
from typing import Self

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

LOGGER = logging.getLogger(__name__)


class MqttConnectionError(ConnectionError):
    """Raised when the MQTT broker rejects or times out a connection."""


class MqttPublisher:
    """Small lifecycle wrapper around the Paho MQTT client."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        *,
        keepalive: int = 60,
        connect_timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._connect_timeout = connect_timeout
        self._connected = threading.Event()
        self._connection_error: str | None = None
        self._client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv5,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def connect(self) -> None:
        """Connect and wait until the broker acknowledges the session."""
        self._connected.clear()
        self._connection_error = None
        self._client.connect(self._host, self._port, self._keepalive)
        self._client.loop_start()
        if not self._connected.wait(self._connect_timeout):
            self.close()
            detail = self._connection_error or "connection acknowledgement timed out"
            raise MqttConnectionError(f"Could not connect to MQTT broker: {detail}")

    def publish(self, topic: str, payload: bytes, *, qos: int = 1) -> None:
        """Publish one message and wait for the client to hand it off."""
        if not self._connected.is_set():
            raise MqttConnectionError("MQTT publisher is not connected")
        result = self._client.publish(topic, payload=payload, qos=qos, retain=False)
        result.wait_for_publish(timeout=10.0)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MqttConnectionError(f"MQTT publish failed with result code {result.rc}")
        if not result.is_published():
            raise MqttConnectionError("MQTT publish acknowledgement timed out")

    def close(self) -> None:
        """Stop networking and close the broker connection."""
        if self._connected.is_set():
            self._client.disconnect()
        self._client.loop_stop()
        self._connected.clear()

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        del client, userdata, flags, properties
        if reason_code.is_failure:
            self._connection_error = str(reason_code)
            LOGGER.error("mqtt_connect_failed", extra={"reason": str(reason_code)})
            return
        LOGGER.info("mqtt_connected", extra={"host": self._host, "port": self._port})
        self._connected.set()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        del client, userdata, disconnect_flags, properties
        self._connected.clear()
        if reason_code.is_failure:
            LOGGER.warning("mqtt_disconnected", extra={"reason": str(reason_code)})
