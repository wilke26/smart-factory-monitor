"""Append-only, hash-chained PostgreSQL audit trail for privileged operations."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from smart_factory.domain.operator_audit import (
    AuditChainVerification,
    AuditState,
    AuditValue,
    OperatorAction,
    OperatorActionOutcome,
    OperatorAuditEvent,
)
from smart_factory.infrastructure.database._pool import ConnectionPoolLike, create_pool

GENESIS_HASH = "0" * 64
LOCK_AUDIT_CHAIN = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
SELECT_AUDIT_HEAD = """
SELECT event_hash
FROM operator_audit_events
ORDER BY sequence_number DESC
LIMIT 1
"""
INSERT_AUDIT_EVENT = """
INSERT INTO operator_audit_events (
    event_id,
    occurred_at,
    actor,
    reason,
    correlation_id,
    action,
    outcome,
    previous_state,
    resulting_state,
    error_type,
    previous_hash,
    event_hash
)
VALUES (%s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), CAST(%s AS jsonb), %s, %s, %s)
"""
SELECT_AUDIT_CHAIN = """
SELECT
    sequence_number,
    event_id,
    occurred_at,
    actor,
    reason,
    correlation_id,
    action,
    outcome,
    previous_state,
    resulting_state,
    error_type,
    previous_hash,
    event_hash
FROM operator_audit_events
ORDER BY sequence_number
"""


def _state_document(state: AuditState) -> dict[str, AuditValue]:
    return dict(state)


def _normalized_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def canonical_event_document(event: OperatorAuditEvent) -> dict[str, object]:
    return {
        "action": event.action.value,
        "actor": event.actor,
        "correlation_id": str(event.correlation_id),
        "error_type": event.error_type,
        "event_id": str(event.event_id),
        "occurred_at": _normalized_timestamp(event.occurred_at),
        "outcome": event.outcome.value,
        "previous_state": _state_document(event.previous_state),
        "reason": event.reason,
        "resulting_state": _state_document(event.resulting_state),
    }


def event_hash(previous_hash: str, event: OperatorAuditEvent) -> str:
    document = json.dumps(
        canonical_event_document(event),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(f"{previous_hash}\n{document}".encode()).hexdigest()


class PsycopgOperatorAuditTrail:
    """Serialize writers and persist a verifiable SHA-256 event chain."""

    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 4,
        pool: ConnectionPoolLike | None = None,
    ) -> None:
        self._pool = pool or create_pool(
            database_url,
            min_size=min_size,
            max_size=max_size,
            name="operator-audit-pool",
        )

    def open(self, *, timeout: float = 10.0) -> None:
        self._pool.open(wait=True, timeout=timeout)

    def close(self) -> None:
        self._pool.close()

    def append(self, event: OperatorAuditEvent) -> None:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(LOCK_AUDIT_CHAIN, ("smart-factory-operator-audit",))
            cursor.execute(SELECT_AUDIT_HEAD)
            row = cursor.fetchone()
            previous_hash = cast(str, row[0]) if row is not None else GENESIS_HASH
            digest = event_hash(previous_hash, event)
            cursor.execute(
                INSERT_AUDIT_EVENT,
                (
                    event.event_id,
                    event.occurred_at,
                    event.actor,
                    event.reason,
                    event.correlation_id,
                    event.action.value,
                    event.outcome.value,
                    json.dumps(_state_document(event.previous_state), separators=(",", ":")),
                    json.dumps(_state_document(event.resulting_state), separators=(",", ":")),
                    event.error_type,
                    previous_hash,
                    digest,
                ),
            )

    def verify(self) -> AuditChainVerification:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(SELECT_AUDIT_CHAIN)
            rows = cursor.fetchall()
        previous_hash = GENESIS_HASH
        for row in rows:
            sequence_number = cast(int, row[0])
            event = OperatorAuditEvent(
                event_id=cast(UUID, row[1]),
                occurred_at=cast(datetime, row[2]),
                actor=cast(str, row[3]),
                reason=cast(str, row[4]),
                correlation_id=cast(UUID, row[5]),
                action=OperatorAction(cast(str, row[6])),
                outcome=OperatorActionOutcome(cast(str, row[7])),
                previous_state=_state_from_json(row[8]),
                resulting_state=_state_from_json(row[9]),
                error_type=cast(str | None, row[10]),
            )
            stored_previous_hash = cast(str, row[11])
            stored_event_hash = cast(str, row[12])
            if stored_previous_hash != previous_hash or stored_event_hash != event_hash(
                previous_hash, event
            ):
                return AuditChainVerification(
                    valid=False,
                    event_count=len(rows),
                    head_hash=previous_hash,
                    invalid_sequence_number=sequence_number,
                )
            previous_hash = stored_event_hash
        return AuditChainVerification(
            valid=True,
            event_count=len(rows),
            head_hash=previous_hash,
        )


def _state_from_json(value: object) -> AuditState:
    document = json.loads(value) if isinstance(value, str) else cast(dict[str, Any], value)
    return tuple(
        (key, tuple(item) if isinstance(item, list) else cast(AuditValue, item))
        for key, item in sorted(document.items())
    )
