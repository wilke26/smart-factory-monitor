import threading
from types import TracebackType
from typing import ClassVar, Self
from unittest.mock import patch

from smart_factory.config import Settings
from smart_factory.main import run


def settings() -> Settings:
    return Settings(
        mqtt_host="broker",
        mqtt_port=1883,
        mqtt_keepalive=60,
        mqtt_qos=1,
        mqtt_client_id="test-client",
        mqtt_consumer_client_id="test-consumer",
        mqtt_topic_filter="factory/+/+/telemetry",
        factory_area="hall-a",
        machine_id="press-01",
        publish_interval_seconds=0.01,
        simulator_seed=42,
        log_level="INFO",
        database_url="postgresql://unused",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
        maximum_temperature_c=90,
        maximum_vibration_mm_s=7,
        maximum_power_kw=30,
        minimum_production_rate=25,
    )


class RecordingPublisher:
    published: ClassVar[list[tuple[str, bytes, int]]] = []
    stop_event: threading.Event

    def __init__(self, host: str, port: int, client_id: str, *, keepalive: int = 60) -> None:
        del host, port, client_id, keepalive

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def publish(self, topic: str, payload: bytes, *, qos: int = 1) -> None:
        self.published.append((topic, payload, qos))
        self.stop_event.set()


def test_run_publishes_until_stop_is_requested() -> None:
    stop_event = threading.Event()
    RecordingPublisher.published = []
    RecordingPublisher.stop_event = stop_event

    with patch("smart_factory.main.MqttPublisher", RecordingPublisher):
        run(settings(), stop_event)

    assert len(RecordingPublisher.published) == 1
    topic, payload, qos = RecordingPublisher.published[0]
    assert topic == "factory/hall-a/press-01/telemetry"
    assert b'"machine_id":"press-01"' in payload
    assert qos == 1
