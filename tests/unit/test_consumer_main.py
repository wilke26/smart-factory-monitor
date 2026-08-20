import threading
from contextlib import suppress
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from psycopg_pool import PoolTimeout

import smart_factory.consumer_main as consumer_main
from smart_factory.config import MlSettings, Settings
from smart_factory.consumer_main import build_anomaly_detector, run
from smart_factory.infrastructure.ml.isolation_forest import MlArtifactError


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
        maximum_temperature_c=90,
        maximum_vibration_mm_s=7,
        maximum_power_kw=30,
        minimum_production_rate=25,
    )


def ml_settings(*, enabled: bool = False) -> MlSettings:
    return MlSettings(
        enabled=enabled,
        model_path="/models/model.joblib",
        machine_id="press-01",
        contamination=0.05,
        minimum_training_samples=100,
        training_limit=10_000,
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


def test_main_retries_database_startup_timeout() -> None:
    stop_event = Mock()
    stop_event.is_set.side_effect = [False, True]
    logger = Mock()

    with (
        patch.object(consumer_main.Settings, "from_env", return_value=settings()),
        patch.object(consumer_main, "configure_logging"),
        patch.object(consumer_main.threading, "Event", return_value=stop_event),
        patch.object(consumer_main.signal, "signal"),
        patch.object(consumer_main, "run", side_effect=PoolTimeout("database unavailable")),
        patch.object(consumer_main, "MonitoringServer"),
        patch.object(consumer_main, "LOGGER", logger),
    ):
        consumer_main.main()

    stop_event.wait.assert_called_once_with(1.0)
    assert logger.warning.call_args.args[0] == "service_unavailable"
    assert logger.warning.call_args.kwargs["extra"]["retry_seconds"] == 1.0


def test_main_does_not_retry_permanent_ml_artifact_error() -> None:
    stop_event = Mock()
    stop_event.is_set.return_value = False
    logger = Mock()

    with (
        patch.object(consumer_main.Settings, "from_env", return_value=settings()),
        patch.object(consumer_main, "configure_logging"),
        patch.object(consumer_main.threading, "Event", return_value=stop_event),
        patch.object(consumer_main.signal, "signal"),
        patch.object(consumer_main, "MonitoringServer"),
        patch.object(
            consumer_main,
            "run",
            side_effect=MlArtifactError("model artifact is missing"),
        ),
        patch.object(consumer_main, "LOGGER", logger),
        pytest.raises(MlArtifactError, match="artifact is missing"),
    ):
        consumer_main.main()

    stop_event.wait.assert_not_called()
    logger.warning.assert_not_called()


def test_rule_detector_remains_available_when_ml_is_disabled() -> None:
    detector = build_anomaly_detector(settings(), ml_settings())

    assert (
        detector.evaluate(Mock(temperature_c=70, vibration_mm_s=2, power_kw=15, production_rate=40))
        == ()
    )


@patch("smart_factory.infrastructure.ml.isolation_forest.IsolationForestAnomalyDetector.load")
def test_loads_ml_model_only_when_enabled(load: Mock) -> None:
    load.return_value.evaluate.return_value = ()

    build_anomaly_detector(settings(), ml_settings(enabled=True))

    load.assert_called_once_with(
        Path("/models/model.joblib"),
        expected_machine_id="press-01",
    )
