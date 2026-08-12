"""Console entry point for the machine simulator."""

import logging
import signal
import threading
from time import sleep

from smart_factory.config import Settings
from smart_factory.infrastructure.mqtt.publisher import MqttPublisher
from smart_factory.simulator.machine import MachineSimulator

LOGGER = logging.getLogger(__name__)


def run(settings: Settings, stop_event: threading.Event | None = None) -> None:
    """Publish measurements until a termination signal is received."""
    should_stop = stop_event or threading.Event()
    simulator = MachineSimulator(settings.machine_id, seed=settings.simulator_seed)
    publisher = MqttPublisher(
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_client_id,
        keepalive=settings.mqtt_keepalive,
    )

    LOGGER.info("Publishing %s telemetry to %s", settings.machine_id, settings.topic)
    with publisher:
        while not should_stop.is_set():
            measurement = simulator.next_measurement()
            publisher.publish(
                settings.topic,
                measurement.to_mqtt_payload(),
                qos=settings.mqtt_qos,
            )
            LOGGER.info("Published: %s", measurement.model_dump_json())
            should_stop.wait(settings.publish_interval_seconds)


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del frame
        LOGGER.info("Received signal %d; stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    retry_delay = 1.0
    while not stop_event.is_set():
        try:
            run(settings, stop_event)
        except (ConnectionError, OSError) as exc:
            LOGGER.warning("MQTT unavailable (%s); retrying in %.0f seconds", exc, retry_delay)
            sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


if __name__ == "__main__":
    main()
