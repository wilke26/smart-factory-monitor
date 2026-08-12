import threading
from contextlib import suppress
from unittest.mock import Mock, patch

from smart_factory.config import Settings
from smart_factory.consumer_main import run


def settings() -> Settings:
    return Settings(
        mqtt_host="broker",
        mqtt_port=1883,
        mqtt_keepalive=60,
        mqtt_qos=1,
        mqtt_client_id="publisher",
        mqtt_consumer_client_id="consumer",
        mqtt_topic_filter="factory/+/+/telemetry",
        factory_area="hall-a",
        machine_id="press-01",
        publish_interval_seconds=1,
        simulator_seed=None,
        log_level="INFO",
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )


@patch("smart_factory.consumer_main.PsycopgTelemetryRepository")
@patch("smart_factory.consumer_main.MqttTelemetryConsumer")
def test_run_connects_waits_and_closes(consumer_type: Mock, repository_type: Mock) -> None:
    stop_event = threading.Event()
    stop_event.set()

    run(settings(), stop_event)

    consumer_type.return_value.connect.assert_called_once()
    consumer_type.return_value.close.assert_called_once()
    repository_type.return_value.open.assert_called_once_with(timeout=10)
    repository_type.return_value.close.assert_called_once()


@patch("smart_factory.consumer_main.PsycopgTelemetryRepository")
@patch("smart_factory.consumer_main.MqttTelemetryConsumer")
def test_run_closes_after_connect_failure(consumer_type: Mock, repository_type: Mock) -> None:
    consumer_type.return_value.connect.side_effect = RuntimeError("cannot connect")

    with suppress(RuntimeError):
        run(settings(), threading.Event())

    consumer_type.return_value.close.assert_called_once()
    repository_type.return_value.close.assert_called_once()
