from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from smart_factory.application.ports.alerts import AlertLeaseLostError
from smart_factory.infrastructure.database.alert_outbox import (
    CLAIM_ALERTS,
    MARK_ALERT_DELIVERED,
    RESCHEDULE_ALERT,
    PsycopgAlertOutbox,
)

EVENT_ID = UUID("11111111-1111-1111-1111-111111111111")
LEASE_TOKEN = UUID("22222222-2222-2222-2222-222222222222")
RECORDED_AT = datetime(2026, 8, 25, tzinfo=UTC)


def outbox_with_pool() -> tuple[PsycopgAlertOutbox, MagicMock, MagicMock]:
    pool = MagicMock()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    return PsycopgAlertOutbox("unused", pool=pool), pool, cursor


def test_opens_and_closes_pool() -> None:
    outbox, pool, _ = outbox_with_pool()

    outbox.open(timeout=7)
    outbox.close()

    pool.open.assert_called_once_with(wait=True, timeout=7)
    pool.close.assert_called_once()


def test_claims_and_maps_a_bounded_alert_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    outbox, _, cursor = outbox_with_pool()
    cursor.fetchall.return_value = [
        (
            EVENT_ID,
            "press-01",
            RECORDED_AT,
            "temperature-high",
            "high",
            "temperature_c",
            95.0,
            90.0,
            ">",
            "temperature exceeds maximum",
            2,
        )
    ]
    monkeypatch.setattr(
        "smart_factory.infrastructure.database.alert_outbox.uuid4",
        lambda: LEASE_TOKEN,
    )

    claimed = outbox.claim(limit=20, lease_seconds=30)

    cursor.execute.assert_called_once_with(CLAIM_ALERTS, (20, LEASE_TOKEN, 30))
    assert len(claimed) == 1
    assert claimed[0].alert.event_id == EVENT_ID
    assert claimed[0].alert.machine_id == "press-01"
    assert claimed[0].attempt_number == 2
    assert claimed[0].lease_token == LEASE_TOKEN


def test_marks_only_the_owned_lease_as_delivered() -> None:
    outbox, _, cursor = outbox_with_pool()
    cursor.fetchall.return_value = [
        (
            EVENT_ID,
            "press-01",
            RECORDED_AT,
            "temperature-high",
            "high",
            "temperature_c",
            95.0,
            90.0,
            ">",
            "temperature exceeds maximum",
            1,
        )
    ]
    cursor.rowcount = 1
    claimed = PsycopgAlertOutbox._claimed_alert(cursor.fetchall.return_value[0], LEASE_TOKEN)

    outbox.mark_delivered(claimed)

    cursor.execute.assert_called_once_with(
        MARK_ALERT_DELIVERED,
        ("press-01", RECORDED_AT, "temperature-high", LEASE_TOKEN),
    )


def test_reschedule_records_bounded_error_and_rejects_lost_lease() -> None:
    outbox, _, cursor = outbox_with_pool()
    row = (
        EVENT_ID,
        "press-01",
        RECORDED_AT,
        "temperature-high",
        "high",
        "temperature_c",
        95.0,
        90.0,
        ">",
        "temperature exceeds maximum",
        1,
    )
    claimed = PsycopgAlertOutbox._claimed_alert(row, LEASE_TOKEN)
    cursor.rowcount = 0

    with pytest.raises(AlertLeaseLostError, match=str(EVENT_ID)):
        outbox.reschedule(claimed, delay_seconds=5, error="x" * 200)

    cursor.execute.assert_called_once_with(
        RESCHEDULE_ALERT,
        (5, "x" * 128, "press-01", RECORDED_AT, "temperature-high", LEASE_TOKEN),
    )
