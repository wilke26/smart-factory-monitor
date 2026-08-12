"""Console entry point for the MQTT telemetry consumer."""

import logging
import signal
import threading

from smart_factory.application.services.telemetry import TelemetryApplicationService
from smart_factory.config import Settings
from smart_factory.infrastructure.mqtt.consumer import MqttTelemetryConsumer
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(settings: Settings, stop_event: threading.Event) -> None:
    """Consume telemetry until a termination signal is received."""
    service = TelemetryApplicationService()
    consumer = MqttTelemetryConsumer(
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_consumer_client_id,
        settings.mqtt_topic_filter,
        service,
        qos=settings.mqtt_qos,
        keepalive=settings.mqtt_keepalive,
    )
    try:
        consumer.connect()
        stop_event.wait()
    finally:
        consumer.close()


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del frame
        LOGGER.info("shutdown_requested", extra={"signal": signum})
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    retry_delay = 1.0
    while not stop_event.is_set():
        try:
            run(settings, stop_event)
        except (ConnectionError, OSError) as error:
            LOGGER.warning(
                "mqtt_unavailable",
                extra={"reason": str(error), "retry_seconds": retry_delay},
            )
            stop_event.wait(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


if __name__ == "__main__":
    main()
