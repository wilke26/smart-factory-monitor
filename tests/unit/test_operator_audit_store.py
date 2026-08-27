from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

from smart_factory.domain.operator_audit import (
    OperatorAction,
    OperatorActionOutcome,
    OperatorAuditEvent,
)
from smart_factory.infrastructure.database.operator_audit import (
    GENESIS_HASH,
    INSERT_AUDIT_EVENT,
    LOCK_AUDIT_CHAIN,
    SELECT_AUDIT_CHAIN,
    SELECT_AUDIT_HEAD,
    PsycopgOperatorAuditTrail,
    event_hash,
)


def trail_with_pool() -> tuple[PsycopgOperatorAuditTrail, MagicMock, MagicMock]:
    pool = MagicMock()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    return PsycopgOperatorAuditTrail("unused", pool=pool), pool, cursor


def event(outcome: OperatorActionOutcome = OperatorActionOutcome.STARTED) -> OperatorAuditEvent:
    return OperatorAuditEvent(
        event_id=UUID("11111111-1111-1111-1111-111111111111"),
        occurred_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
        actor="release-bot",
        reason="ticket-123",
        correlation_id=UUID("22222222-2222-2222-2222-222222222222"),
        action=OperatorAction.MODEL_PROMOTION,
        outcome=outcome,
        resulting_state=(("machine_ids", ("press-01",)),),
    )


def row(sequence_number: int, record: OperatorAuditEvent, previous_hash: str) -> tuple[object, ...]:
    return (
        sequence_number,
        record.event_id,
        record.occurred_at,
        record.actor,
        record.reason,
        record.correlation_id,
        record.action.value,
        record.outcome.value,
        dict(record.previous_state),
        dict(record.resulting_state),
        record.error_type,
        previous_hash,
        event_hash(previous_hash, record),
    )


def test_opens_and_closes_bounded_pool() -> None:
    trail, pool, _ = trail_with_pool()

    trail.open(timeout=7)
    trail.close()

    pool.open.assert_called_once_with(wait=True, timeout=7)
    pool.close.assert_called_once()


def test_serializes_writer_and_appends_hash_chained_event() -> None:
    trail, _, cursor = trail_with_pool()
    cursor.fetchone.return_value = None
    record = event()

    trail.append(record)

    assert cursor.execute.call_args_list[0].args == (
        LOCK_AUDIT_CHAIN,
        ("smart-factory-operator-audit",),
    )
    assert cursor.execute.call_args_list[1].args == (SELECT_AUDIT_HEAD,)
    query, params = cursor.execute.call_args_list[2].args
    assert query == INSERT_AUDIT_EVENT
    assert params[-2:] == (GENESIS_HASH, event_hash(GENESIS_HASH, record))


def test_verifies_complete_chain_and_identifies_tampering() -> None:
    trail, _, cursor = trail_with_pool()
    first = event()
    second = first.model_copy(
        update={
            "event_id": UUID("33333333-3333-3333-3333-333333333333"),
            "outcome": OperatorActionOutcome.SUCCEEDED,
        }
    )
    first_row = row(1, first, GENESIS_HASH)
    first_hash = first_row[-1]
    second_row = row(2, second, str(first_hash))
    cursor.fetchall.return_value = [first_row, second_row]

    valid = trail.verify()

    cursor.execute.assert_called_once_with(SELECT_AUDIT_CHAIN)
    assert valid.valid is True
    assert valid.event_count == 2
    assert valid.head_hash == second_row[-1]

    cursor.fetchall.return_value = [first_row, (*second_row[:-1], "f" * 64)]
    invalid = trail.verify()

    assert invalid.valid is False
    assert invalid.invalid_sequence_number == 2
