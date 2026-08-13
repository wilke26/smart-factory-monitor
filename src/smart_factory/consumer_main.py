"""Console entry point for the MQTT telemetry consumer."""

import logging
import signal
import threading

from psycopg import OperationalError

from smart_factory.application.ports.anomaly import AnomalyDetector
from smart_factory.application.services.anomaly_detection import CompositeAnomalyDetector
from smart_factory.application.services.telemetry import TelemetryApplicationService
from smart_factory.config import MlSettings, Settings
from smart_factory.domain.services.anomaly_detection import (
    AnomalyThresholds,
    RuleBasedAnomalyDetector,
)
from smart_factory.infrastructure.database.telemetry_repository import PsycopgTelemetryRepository
from smart_factory.infrastructure.mqtt.consumer import MqttTelemetryConsumer
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def build_anomaly_detector(
    settings: Settings,
    ml_settings: MlSettings,
) -> CompositeAnomalyDetector:
    detectors: list[AnomalyDetector] = [
        RuleBasedAnomalyDetector(
            AnomalyThresholds(
                maximum_temperature_c=settings.maximum_temperature_c,
                maximum_vibration_mm_s=settings.maximum_vibration_mm_s,
                maximum_power_kw=settings.maximum_power_kw,
                minimum_production_rate=settings.minimum_production_rate,
            )
        )
    ]
    if ml_settings.enabled:
        from pathlib import Path

        from smart_factory.infrastructure.ml.isolation_forest import (
            IsolationForestAnomalyDetector,
        )

        detectors.append(IsolationForestAnomalyDetector.load(Path(ml_settings.model_path)))
    return CompositeAnomalyDetector(tuple(detectors))


def run(
    settings: Settings,
    stop_event: threading.Event,
    ml_settings: MlSettings | None = None,
) -> None:
    """Consume telemetry until a termination signal is received."""
    detector = build_anomaly_detector(settings, ml_settings or MlSettings.from_env())
    repository = PsycopgTelemetryRepository(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    service = TelemetryApplicationService(repository=repository, anomaly_detector=detector)
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
        repository.open(timeout=settings.database_connect_timeout_seconds)
        consumer.connect()
        stop_event.wait()
    finally:
        consumer.close()
        repository.close()


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
        except (ConnectionError, OSError, OperationalError) as error:
            LOGGER.warning(
                "service_unavailable",
                extra={"reason": str(error), "retry_seconds": retry_delay},
            )
            stop_event.wait(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


if __name__ == "__main__":
    main()
