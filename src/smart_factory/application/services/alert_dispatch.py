"""Application service for leased, retryable alert delivery."""

import logging

from smart_factory.application.ports.alerts import AlertOutbox, AlertSink


class AlertDispatcher:
    """Deliver one bounded outbox batch with exponential retry scheduling."""

    def __init__(
        self,
        *,
        outbox: AlertOutbox,
        sink: AlertSink,
        batch_size: int,
        lease_seconds: int,
        retry_base_seconds: float,
        retry_max_seconds: float,
        logger: logging.Logger | None = None,
    ) -> None:
        self._outbox = outbox
        self._sink = sink
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._logger = logger or logging.getLogger(__name__)

    def dispatch_once(self) -> int:
        claimed_alerts = self._outbox.claim(
            limit=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        delivered = 0
        for claimed in claimed_alerts:
            alert = claimed.alert
            try:
                self._sink.send(alert)
            except Exception as error:
                delay = min(
                    self._retry_base_seconds * 2 ** min(claimed.attempt_number - 1, 30),
                    self._retry_max_seconds,
                )
                error_name = type(error).__name__
                self._outbox.reschedule(
                    claimed,
                    delay_seconds=delay,
                    error=error_name,
                )
                self._logger.warning(
                    "anomaly_alert_failed",
                    extra={
                        "event_id": str(alert.event_id),
                        "attempt_number": claimed.attempt_number,
                        "retry_seconds": delay,
                        "error_type": error_name,
                    },
                )
                continue
            self._outbox.mark_delivered(claimed)
            delivered += 1
            self._logger.info(
                "anomaly_alert_delivered",
                extra={
                    "event_id": str(alert.event_id),
                    "attempt_number": claimed.attempt_number,
                },
            )
        return delivered
