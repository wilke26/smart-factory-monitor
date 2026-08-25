from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

from smart_factory.application.ports.alerts import ClaimedAlert
from smart_factory.application.services.alert_dispatch import AlertDispatcher
from smart_factory.domain.alert import AnomalyAlert
from smart_factory.domain.anomaly import AnomalySeverity


def alert() -> AnomalyAlert:
    return AnomalyAlert(
        event_id=uuid4(),
        machine_id="press-01",
        recorded_at=datetime(2026, 8, 25, tzinfo=UTC),
        rule_id="temperature-high",
        severity=AnomalySeverity.HIGH,
        metric="temperature_c",
        observed_value=95.0,
        threshold=90.0,
        comparison=">",
        message="temperature exceeds maximum",
    )


def claimed(*, attempt_number: int = 1) -> ClaimedAlert:
    return ClaimedAlert(
        alert=alert(),
        lease_token=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        attempt_number=attempt_number,
    )


def dispatcher(outbox: Mock, sink: Mock, logger: Mock) -> AlertDispatcher:
    return AlertDispatcher(
        outbox=outbox,
        sink=sink,
        batch_size=20,
        lease_seconds=30,
        retry_base_seconds=5,
        retry_max_seconds=300,
        logger=logger,
    )


def test_delivers_and_marks_a_claimed_alert() -> None:
    outbox = Mock()
    sink = Mock()
    logger = Mock()
    item = claimed()
    outbox.claim.return_value = (item,)

    delivered = dispatcher(outbox, sink, logger).dispatch_once()

    assert delivered == 1
    outbox.claim.assert_called_once_with(limit=20, lease_seconds=30)
    sink.send.assert_called_once_with(item.alert)
    outbox.mark_delivered.assert_called_once_with(item)
    outbox.reschedule.assert_not_called()
    assert logger.info.call_args.args[0] == "anomaly_alert_delivered"


def test_reschedules_failed_delivery_without_leaking_exception_text() -> None:
    outbox = Mock()
    sink = Mock()
    logger = Mock()
    item = claimed(attempt_number=3)
    outbox.claim.return_value = (item,)
    sink.send.side_effect = OSError("secret response body")

    delivered = dispatcher(outbox, sink, logger).dispatch_once()

    assert delivered == 0
    outbox.reschedule.assert_called_once_with(
        item,
        delay_seconds=20,
        error="OSError",
    )
    outbox.mark_delivered.assert_not_called()
    assert "secret response body" not in str(logger.warning.call_args)


def test_caps_retry_delay_for_large_attempt_number() -> None:
    outbox = Mock()
    sink = Mock()
    sink.send.side_effect = RuntimeError("unavailable")
    item = claimed(attempt_number=1_000_000)
    outbox.claim.return_value = (item,)

    dispatcher(outbox, sink, Mock()).dispatch_once()

    outbox.reschedule.assert_called_once_with(
        item,
        delay_seconds=300,
        error="RuntimeError",
    )
