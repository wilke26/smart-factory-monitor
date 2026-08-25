"""Console entry point for durable anomaly alert delivery."""

import logging
import signal
import threading

from psycopg import OperationalError

from smart_factory.application.services.alert_dispatch import AlertDispatcher
from smart_factory.config import AlertSettings, Settings
from smart_factory.infrastructure.alerts.webhook import WebhookAlertSink
from smart_factory.infrastructure.database.alert_outbox import PsycopgAlertOutbox
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def run(
    settings: Settings,
    alert_settings: AlertSettings,
    stop_event: threading.Event,
) -> None:
    if alert_settings.webhook_url is None:
        raise ValueError("ALERT_WEBHOOK_URL is required for the alert dispatcher")
    outbox = PsycopgAlertOutbox(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    sink = WebhookAlertSink(
        alert_settings.webhook_url,
        timeout_seconds=alert_settings.request_timeout_seconds,
        bearer_token=alert_settings.bearer_token,
        ca_cert_path=alert_settings.ca_cert_path,
    )
    dispatcher = AlertDispatcher(
        outbox=outbox,
        sink=sink,
        batch_size=alert_settings.batch_size,
        lease_seconds=alert_settings.lease_seconds,
        retry_base_seconds=alert_settings.retry_base_seconds,
        retry_max_seconds=alert_settings.retry_max_seconds,
    )
    try:
        outbox.open(timeout=settings.database_connect_timeout_seconds)
        while not stop_event.is_set():
            dispatcher.dispatch_once()
            stop_event.wait(alert_settings.poll_interval_seconds)
    finally:
        outbox.close()


def main() -> None:
    settings = Settings.from_env()
    alert_settings = AlertSettings.from_env()
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
            run(settings, alert_settings, stop_event)
        except (ConnectionError, OSError, OperationalError) as error:
            LOGGER.warning(
                "alert_dispatcher_unavailable",
                extra={"error_type": type(error).__name__, "retry_seconds": retry_delay},
            )
            stop_event.wait(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


if __name__ == "__main__":
    main()
