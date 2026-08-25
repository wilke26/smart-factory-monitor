import threading
from unittest.mock import Mock, patch

import pytest

from smart_factory.alert_dispatcher_main import run
from smart_factory.config import AlertSettings
from smart_factory.domain.anomaly import AnomalySeverity


def alert_settings(
    *, webhook_url: str | None = "https://alerts.example.test/events"
) -> AlertSettings:
    return AlertSettings(
        webhook_url=webhook_url,
        minimum_severity=AnomalySeverity.HIGH,
        batch_size=20,
        poll_interval_seconds=2,
        request_timeout_seconds=5,
        lease_seconds=120,
        retry_base_seconds=5,
        retry_max_seconds=300,
    )


def runtime_settings() -> Mock:
    return Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )


@patch("smart_factory.alert_dispatcher_main.AlertDispatcher")
@patch("smart_factory.alert_dispatcher_main.WebhookAlertSink")
@patch("smart_factory.alert_dispatcher_main.PsycopgAlertOutbox")
def test_dispatches_until_stopped_and_closes_outbox(
    outbox_type: Mock,
    sink_type: Mock,
    dispatcher_type: Mock,
) -> None:
    stop_event = Mock()
    stop_event.is_set.side_effect = [False, True]

    run(runtime_settings(), alert_settings(), stop_event)

    outbox_type.assert_called_once_with(
        "postgresql://database/smart_factory",
        min_size=1,
        max_size=4,
    )
    sink_type.assert_called_once_with(
        "https://alerts.example.test/events",
        timeout_seconds=5,
        bearer_token=None,
        ca_cert_path=None,
    )
    dispatcher_type.assert_called_once_with(
        outbox=outbox_type.return_value,
        sink=sink_type.return_value,
        batch_size=20,
        lease_seconds=120,
        retry_base_seconds=5,
        retry_max_seconds=300,
    )
    outbox_type.return_value.open.assert_called_once_with(timeout=10)
    dispatcher_type.return_value.dispatch_once.assert_called_once()
    stop_event.wait.assert_called_once_with(2)
    outbox_type.return_value.close.assert_called_once()


@patch("smart_factory.alert_dispatcher_main.PsycopgAlertOutbox")
def test_closes_outbox_after_database_open_failure(outbox_type: Mock) -> None:
    outbox_type.return_value.open.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        run(runtime_settings(), alert_settings(), threading.Event())

    outbox_type.return_value.close.assert_called_once()


def test_requires_webhook_url_before_creating_outbox() -> None:
    with pytest.raises(ValueError, match="ALERT_WEBHOOK_URL is required"):
        run(runtime_settings(), alert_settings(webhook_url=None), threading.Event())
