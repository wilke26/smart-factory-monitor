"""Psycopg implementation of durable telemetry storage."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Protocol, cast
from uuid import NAMESPACE_URL, uuid5

from smart_factory.application.ports.telemetry import TelemetryIdentityConflictError
from smart_factory.domain.anomaly import AnomalyFinding
from smart_factory.domain.telemetry import TelemetryReading

INSERT_TELEMETRY = """
INSERT INTO telemetry_readings (
    machine_id,
    recorded_at,
    temperature_c,
    vibration_mm_s,
    power_kw,
    production_rate
)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (machine_id, recorded_at) DO NOTHING
"""

INSERT_ANOMALY = """
INSERT INTO anomaly_findings (
    machine_id,
    recorded_at,
    rule_id,
    severity,
    metric,
    observed_value,
    threshold,
    comparison,
    message
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (machine_id, recorded_at, rule_id) DO NOTHING
"""

INSERT_ALERT_OUTBOX = """
INSERT INTO anomaly_alert_outbox (
    event_id,
    machine_id,
    recorded_at,
    rule_id,
    severity,
    metric,
    observed_value,
    threshold,
    comparison,
    message
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (machine_id, recorded_at, rule_id) DO NOTHING
"""

SELECT_RECENT_TELEMETRY = """
SELECT
    machine_id,
    recorded_at,
    temperature_c,
    vibration_mm_s,
    power_kw,
    production_rate
FROM telemetry_readings
WHERE machine_id = %s
ORDER BY recorded_at DESC
LIMIT %s
"""

SELECT_TELEMETRY_SINCE = """
SELECT
    machine_id,
    recorded_at,
    temperature_c,
    vibration_mm_s,
    power_kw,
    production_rate
FROM telemetry_readings
WHERE machine_id = %s AND recorded_at > %s
ORDER BY recorded_at DESC
LIMIT %s
"""

SELECT_TELEMETRY_BY_IDENTITY = """
SELECT
    temperature_c,
    vibration_mm_s,
    power_kw,
    production_rate
FROM telemetry_readings
WHERE machine_id = %s AND recorded_at = %s
"""


class CursorLike(Protocol):
    rowcount: int

    def execute(self, query: str, params: tuple[object, ...]) -> CursorLike: ...

    def executemany(self, query: str, params_seq: list[tuple[object, ...]]) -> None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class ConnectionLike(Protocol):
    def cursor(self) -> AbstractContextManager[CursorLike]: ...


class ConnectionPoolLike(Protocol):
    def open(self, *, wait: bool = False, timeout: float = 30.0) -> None: ...

    def connection(self) -> AbstractContextManager[ConnectionLike]: ...

    def close(self) -> None: ...


def _create_pool(database_url: str, *, min_size: int, max_size: int) -> ConnectionPoolLike:
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        open=False,
        check=ConnectionPool.check_connection,
        name="telemetry-pool",
    )
    return cast(ConnectionPoolLike, cast(Any, pool))


class PsycopgTelemetryRepository:
    """Store readings in TimescaleDB through a small connection pool."""

    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 4,
        pool: ConnectionPoolLike | None = None,
        on_availability_change: Callable[[bool], None] | None = None,
        alert_severities: frozenset[str] = frozenset(),
    ) -> None:
        self._pool = pool or _create_pool(
            database_url,
            min_size=min_size,
            max_size=max_size,
        )
        self._on_availability_change = on_availability_change
        self._alert_severities = alert_severities

    def open(self, *, timeout: float = 10.0) -> None:
        """Open the pool and fail fast if the database is not ready."""
        try:
            self._pool.open(wait=True, timeout=timeout)
        except Exception:
            self._record_availability(False)
            raise
        self._record_availability(True)

    def close(self) -> None:
        try:
            self._pool.close()
        finally:
            self._record_availability(False)

    def save(
        self,
        reading: TelemetryReading,
        findings: tuple[AnomalyFinding, ...],
    ) -> bool:
        """Atomically insert a reading and its explainable anomaly findings."""
        parameters: tuple[object, ...] = (
            reading.machine_id,
            reading.timestamp,
            reading.temperature_c,
            reading.vibration_mm_s,
            reading.power_kw,
            reading.production_rate,
        )
        try:
            with self._pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute(INSERT_TELEMETRY, parameters)
                inserted = cursor.rowcount == 1
                if not inserted:
                    cursor.execute(
                        SELECT_TELEMETRY_BY_IDENTITY,
                        (reading.machine_id, reading.timestamp),
                    )
                    persisted = cursor.fetchone()
                    expected = (
                        reading.temperature_c,
                        reading.vibration_mm_s,
                        reading.power_kw,
                        reading.production_rate,
                    )
                    if persisted is None or persisted != expected:
                        raise TelemetryIdentityConflictError(
                            "telemetry identity conflict for "
                            f"{reading.machine_id} at {reading.timestamp.isoformat()}"
                        )
                if findings:
                    cursor.executemany(
                        INSERT_ANOMALY,
                        [
                            (
                                reading.machine_id,
                                reading.timestamp,
                                finding.rule_id,
                                finding.severity.value,
                                finding.metric,
                                finding.observed_value,
                                finding.threshold,
                                finding.comparison,
                                finding.message,
                            )
                            for finding in findings
                        ],
                    )
                    alert_findings = tuple(
                        finding
                        for finding in findings
                        if finding.severity.value in self._alert_severities
                    )
                    if alert_findings:
                        cursor.executemany(
                            INSERT_ALERT_OUTBOX,
                            [
                                (
                                    uuid5(
                                        NAMESPACE_URL,
                                        (
                                            "smart-factory-alert:"
                                            f"{reading.machine_id}:"
                                            f"{reading.timestamp.isoformat()}:"
                                            f"{finding.rule_id}"
                                        ),
                                    ),
                                    reading.machine_id,
                                    reading.timestamp,
                                    finding.rule_id,
                                    finding.severity.value,
                                    finding.metric,
                                    finding.observed_value,
                                    finding.threshold,
                                    finding.comparison,
                                    finding.message,
                                )
                                for finding in alert_findings
                            ],
                        )
        except TelemetryIdentityConflictError:
            self._record_availability(True)
            raise
        except Exception:
            self._record_availability(False)
            raise
        self._record_availability(True)
        return inserted

    def load_recent_readings(self, machine_id: str, limit: int) -> list[TelemetryReading]:
        """Load bounded historical training data without leaking SQL to the trainer."""
        try:
            with self._pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute(SELECT_RECENT_TELEMETRY, (machine_id, limit))
                rows = cursor.fetchall()
        except Exception:
            self._record_availability(False)
            raise
        self._record_availability(True)
        return self._readings_from_rows(rows)

    def load_readings_since(
        self,
        machine_id: str,
        since: datetime,
        limit: int,
    ) -> list[TelemetryReading]:
        """Load a bounded post-training evaluation window for one machine."""
        try:
            with self._pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute(SELECT_TELEMETRY_SINCE, (machine_id, since, limit))
                rows = cursor.fetchall()
        except Exception:
            self._record_availability(False)
            raise
        self._record_availability(True)
        return self._readings_from_rows(rows)

    @staticmethod
    def _readings_from_rows(rows: list[tuple[object, ...]]) -> list[TelemetryReading]:
        return [
            TelemetryReading(
                machine_id=cast(str, row[0]),
                timestamp=cast(Any, row[1]),
                temperature_c=cast(float, row[2]),
                vibration_mm_s=cast(float, row[3]),
                power_kw=cast(float, row[4]),
                production_rate=cast(int, row[5]),
            )
            for row in rows
        ]

    def _record_availability(self, available: bool) -> None:
        if self._on_availability_change is not None:
            self._on_availability_change(available)
