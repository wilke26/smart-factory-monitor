"""Inbound MQTT adapter for telemetry."""

import logging
import threading
from collections.abc import Callable

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode
from pydantic import ValidationError

from smart_factory.application.ports.telemetry import (
    TelemetryHandler,
    TelemetryIdentityConflictError,
)
from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.mqtt.publisher import MqttConnectionError


class MqttTelemetryConsumer:
    """Decode and validate MQTT messages before invoking the application port."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        topic_filter: str,
        handler: TelemetryHandler,
        *,
        qos: int = 1,
        keepalive: int = 60,
        connect_timeout: float = 10.0,
        session_expiry_seconds: int = 86_400,
        receive_maximum: int = 20,
        on_connection_change: Callable[[bool], None] | None = None,
        on_message_outcome: Callable[[str], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._topic_filter = topic_filter
        self._handler = handler
        self._qos = qos
        self._keepalive = keepalive
        self._connect_timeout = connect_timeout
        self._session_expiry_seconds = session_expiry_seconds
        self._receive_maximum = receive_maximum
        self._on_connection_change = on_connection_change
        self._on_message_outcome = on_message_outcome
        self._logger = logger or logging.getLogger(__name__)
        self._connected = threading.Event()
        self._connection_error: str | None = None
        self._client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv5,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.manual_ack_set(True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def connect(self) -> None:
        """Connect and wait until the subscription has been registered."""
        self._connected.clear()
        self._record_connection_change(False)
        self._connection_error = None
        properties = Properties(PacketTypes.CONNECT)  # type: ignore[no-untyped-call]
        properties.SessionExpiryInterval = self._session_expiry_seconds
        properties.ReceiveMaximum = self._receive_maximum
        self._client.connect(
            self._host,
            self._port,
            self._keepalive,
            clean_start=False,
            properties=properties,
        )
        self._client.loop_start()
        if not self._connected.wait(self._connect_timeout):
            self.close()
            detail = self._connection_error or "connection acknowledgement timed out"
            raise MqttConnectionError(f"Could not connect MQTT consumer: {detail}")

    def close(self) -> None:
        """Stop networking and close the broker connection."""
        if self._connected.is_set():
            self._client.disconnect()
        self._client.loop_stop()
        self._connected.clear()
        self._record_connection_change(False)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        del userdata, flags, properties
        if reason_code.is_failure:
            self._connection_error = str(reason_code)
            self._logger.error("mqtt_connect_failed", extra={"reason": str(reason_code)})
            return
        result, message_id = client.subscribe(self._topic_filter, qos=self._qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            self._connection_error = f"subscription failed with result code {result}"
            self._logger.error(
                "mqtt_subscribe_failed",
                extra={"topic_filter": self._topic_filter, "result_code": result},
            )
            return
        self._connected.set()
        self._record_connection_change(True)
        self._logger.info(
            "mqtt_subscribed",
            extra={
                "topic_filter": self._topic_filter,
                "qos": self._qos,
                "message_id": message_id,
            },
        )

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
        self._record_connection_change(False)
        if reason_code.is_failure:
            self._logger.warning("mqtt_disconnected", extra={"reason": str(reason_code)})

    def _on_message(self, client: mqtt.Client, userdata: object, message: mqtt.MQTTMessage) -> None:
        del userdata
        reading: TelemetryReading | None = None
        try:
            reading = TelemetryReading.from_mqtt_payload(message.payload)
            topic_machine_id = self._machine_id_from_topic(message.topic)
            if topic_machine_id != reading.machine_id:
                self._logger.warning(
                    "telemetry_rejected_topic_mismatch",
                    extra={
                        "topic": message.topic,
                        "topic_machine_id": topic_machine_id,
                        "payload_machine_id": reading.machine_id,
                    },
                )
                client.ack(message.mid, message.qos)
                self._record_outcome("topic_mismatch")
                return
            self._handler.process(reading)
            client.ack(message.mid, message.qos)
            self._record_outcome("accepted")
            self._logger.info(
                "telemetry_accepted",
                extra={"topic": message.topic, "machine_id": reading.machine_id},
            )
        except TelemetryIdentityConflictError as error:
            self._logger.error(
                "telemetry_rejected_identity_conflict",
                extra={
                    "topic": message.topic,
                    "machine_id": reading.machine_id if reading is not None else None,
                    "reason": str(error),
                },
            )
            client.ack(message.mid, message.qos)
            self._record_outcome("identity_conflict")
        except ValidationError as error:
            self._logger.warning(
                "telemetry_rejected_invalid_payload",
                extra={
                    "topic": message.topic,
                    "payload_size": len(message.payload),
                    "validation_errors": len(error.errors()),
                    "error_types": [item["type"] for item in error.errors()],
                },
            )
            client.ack(message.mid, message.qos)
            self._record_outcome("invalid_payload")
        except ValueError as error:
            self._logger.warning(
                "telemetry_rejected_invalid_topic",
                extra={"topic": message.topic, "reason": str(error)},
            )
            client.ack(message.mid, message.qos)
            self._record_outcome("invalid_topic")
        except Exception:
            self._logger.exception(
                "telemetry_processing_failed",
                extra={
                    "topic": message.topic,
                    "machine_id": reading.machine_id if reading is not None else None,
                },
            )
            self._record_outcome("processing_failed")

    def _record_connection_change(self, connected: bool) -> None:
        if self._on_connection_change is not None:
            self._on_connection_change(connected)

    def _record_outcome(self, outcome: str) -> None:
        if self._on_message_outcome is not None:
            self._on_message_outcome(outcome)

    @staticmethod
    def _machine_id_from_topic(topic: str) -> str:
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != "factory" or parts[3] != "telemetry":
            raise ValueError("expected factory/<area>/<machine>/telemetry")
        return parts[2]
