"""Psycopg implementation of durable telemetry storage."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol, cast

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


class CursorLike(Protocol):
    rowcount: int

    def execute(self, query: str, params: tuple[object, ...]) -> CursorLike: ...

    def executemany(self, query: str, params_seq: list[tuple[object, ...]]) -> None: ...


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
    ) -> None:
        self._pool = pool or _create_pool(
            database_url,
            min_size=min_size,
            max_size=max_size,
        )

    def open(self, *, timeout: float = 10.0) -> None:
        """Open the pool and fail fast if the database is not ready."""
        self._pool.open(wait=True, timeout=timeout)

    def close(self) -> None:
        self._pool.close()

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
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(INSERT_TELEMETRY, parameters)
            inserted = cursor.rowcount == 1
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
        return inserted
