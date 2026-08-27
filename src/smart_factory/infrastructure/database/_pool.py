"""Shared structural types and factory for bounded Psycopg connection pools."""

from contextlib import AbstractContextManager
from typing import Any, Protocol, cast


class CursorLike(Protocol):
    rowcount: int

    def execute(self, query: str, params: tuple[object, ...] = ()) -> "CursorLike": ...

    def executemany(self, query: str, params_seq: list[tuple[object, ...]]) -> None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class ConnectionLike(Protocol):
    def cursor(self) -> AbstractContextManager[CursorLike]: ...


class ConnectionPoolLike(Protocol):
    def open(self, *, wait: bool = False, timeout: float = 30.0) -> None: ...

    def connection(self) -> AbstractContextManager[ConnectionLike]: ...

    def close(self) -> None: ...


def create_pool(
    database_url: str,
    *,
    min_size: int,
    max_size: int,
    name: str,
) -> ConnectionPoolLike:
    from psycopg_pool import ConnectionPool

    return cast(
        ConnectionPoolLike,
        cast(
            Any,
            ConnectionPool(
                database_url,
                min_size=min_size,
                max_size=max_size,
                open=False,
                check=ConnectionPool.check_connection,
                name=name,
            ),
        ),
    )
