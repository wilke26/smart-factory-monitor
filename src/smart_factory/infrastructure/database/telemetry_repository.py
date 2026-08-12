"""Psycopg implementation of durable telemetry storage."""

from contextlib import AbstractContextManager
from typing import Any, Protocol, cast

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


class CursorLike(Protocol):
    rowcount: int


class ConnectionLike(Protocol):
    def execute(self, query: str, params: tuple[object, ...]) -> CursorLike: ...


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

    def save(self, reading: TelemetryReading) -> bool:
        """Insert once using the natural machine/timestamp identity."""
        parameters: tuple[object, ...] = (
            reading.machine_id,
            reading.timestamp,
            reading.temperature_c,
            reading.vibration_mm_s,
            reading.power_kw,
            reading.production_rate,
        )
        with self._pool.connection() as connection:
            cursor = connection.execute(INSERT_TELEMETRY, parameters)
        return cursor.rowcount == 1
