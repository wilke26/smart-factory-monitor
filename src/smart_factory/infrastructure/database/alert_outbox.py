"""Psycopg transactional-outbox adapter for anomaly alerts."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID, uuid4

from smart_factory.application.ports.alerts import AlertLeaseLostError, ClaimedAlert
from smart_factory.domain.alert import AnomalyAlert
from smart_factory.domain.anomaly import AnomalySeverity
from smart_factory.infrastructure.database._pool import ConnectionPoolLike, create_pool

CLAIM_ALERTS = """
WITH pending AS (
    SELECT machine_id, recorded_at, rule_id
    FROM anomaly_alert_outbox
    WHERE delivered_at IS NULL
      AND available_at <= NOW()
      AND (lease_expires_at IS NULL OR lease_expires_at <= NOW())
    ORDER BY available_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT %s
)
UPDATE anomaly_alert_outbox AS outbox
SET lease_token = %s,
    lease_expires_at = NOW() + %s * INTERVAL '1 second',
    attempt_count = outbox.attempt_count + 1
FROM pending
WHERE outbox.machine_id = pending.machine_id
  AND outbox.recorded_at = pending.recorded_at
  AND outbox.rule_id = pending.rule_id
RETURNING
    outbox.event_id,
    outbox.machine_id,
    outbox.recorded_at,
    outbox.rule_id,
    outbox.severity,
    outbox.metric,
    outbox.observed_value,
    outbox.threshold,
    outbox.comparison,
    outbox.message,
    outbox.attempt_count
"""

MARK_ALERT_DELIVERED = """
UPDATE anomaly_alert_outbox
SET delivered_at = NOW(),
    lease_token = NULL,
    lease_expires_at = NULL,
    last_error = NULL
WHERE machine_id = %s
  AND recorded_at = %s
  AND rule_id = %s
  AND lease_token = %s
  AND delivered_at IS NULL
"""

RESCHEDULE_ALERT = """
UPDATE anomaly_alert_outbox
SET available_at = NOW() + %s * INTERVAL '1 second',
    lease_token = NULL,
    lease_expires_at = NULL,
    last_error = %s
WHERE machine_id = %s
  AND recorded_at = %s
  AND rule_id = %s
  AND lease_token = %s
  AND delivered_at IS NULL
"""


def _create_pool(database_url: str, *, min_size: int, max_size: int) -> ConnectionPoolLike:
    return create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        name="alert-outbox-pool",
    )


class PsycopgAlertOutbox:
    """Lease pending alerts and persist delivery state."""

    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 2,
        pool: ConnectionPoolLike | None = None,
    ) -> None:
        self._pool = pool or _create_pool(database_url, min_size=min_size, max_size=max_size)

    def open(self, *, timeout: float = 10.0) -> None:
        self._pool.open(wait=True, timeout=timeout)

    def close(self) -> None:
        self._pool.close()

    def claim(self, *, limit: int, lease_seconds: int) -> tuple[ClaimedAlert, ...]:
        lease_token = uuid4()
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(CLAIM_ALERTS, (limit, lease_token, lease_seconds))
            rows = cursor.fetchall()
        return tuple(self._claimed_alert(row, lease_token) for row in rows)

    def mark_delivered(self, claimed: ClaimedAlert) -> None:
        alert = claimed.alert
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                MARK_ALERT_DELIVERED,
                (
                    alert.machine_id,
                    alert.recorded_at,
                    alert.rule_id,
                    claimed.lease_token,
                ),
            )
            if cursor.rowcount != 1:
                raise AlertLeaseLostError(f"alert lease lost for {alert.event_id}")

    def reschedule(self, claimed: ClaimedAlert, *, delay_seconds: float, error: str) -> None:
        alert = claimed.alert
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                RESCHEDULE_ALERT,
                (
                    delay_seconds,
                    error[:128],
                    alert.machine_id,
                    alert.recorded_at,
                    alert.rule_id,
                    claimed.lease_token,
                ),
            )
            if cursor.rowcount != 1:
                raise AlertLeaseLostError(f"alert lease lost for {alert.event_id}")

    @staticmethod
    def _claimed_alert(row: tuple[object, ...], lease_token: UUID) -> ClaimedAlert:
        return ClaimedAlert(
            alert=AnomalyAlert(
                event_id=cast(UUID, row[0]),
                machine_id=cast(str, row[1]),
                recorded_at=cast(Any, row[2]),
                rule_id=cast(str, row[3]),
                severity=AnomalySeverity(cast(str, row[4])),
                metric=cast(str, row[5]),
                observed_value=cast(float, row[6]),
                threshold=cast(float, row[7]),
                comparison=cast(Literal[">", "<"], row[8]),
                message=cast(str, row[9]),
            ),
            lease_token=lease_token,
            attempt_number=cast(int, row[10]),
        )
