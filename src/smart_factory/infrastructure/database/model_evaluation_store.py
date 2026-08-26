"""Psycopg adapter for durable model-evaluation evidence."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from typing import Any, Protocol, cast

from smart_factory.domain.model_evaluation import ModelEvaluationEvidence

INSERT_MODEL_EVALUATION = """
INSERT INTO model_evaluation_runs (
    evaluation_id,
    evaluated_at,
    model_id,
    machine_id,
    training_window_end,
    sample_count,
    anomaly_rate,
    feature_psi,
    maximum_feature_psi,
    passed,
    failed_gates
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
"""


class CursorLike(Protocol):
    def execute(self, query: str, params: tuple[object, ...]) -> CursorLike: ...


class ConnectionLike(Protocol):
    def cursor(self) -> AbstractContextManager[CursorLike]: ...


class ConnectionPoolLike(Protocol):
    def open(self, *, wait: bool = False, timeout: float = 30.0) -> None: ...

    def connection(self) -> AbstractContextManager[ConnectionLike]: ...

    def close(self) -> None: ...


def _create_pool(database_url: str, *, min_size: int, max_size: int) -> ConnectionPoolLike:
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
                name="model-evaluation-pool",
            ),
        ),
    )


class PsycopgModelEvaluationStore:
    """Persist immutable evaluation records through a bounded connection pool."""

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

    def save(self, evidence: ModelEvaluationEvidence) -> None:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                INSERT_MODEL_EVALUATION,
                (
                    evidence.evaluation_id,
                    evidence.evaluated_at,
                    evidence.model_id,
                    evidence.machine_id,
                    evidence.training_window_end,
                    evidence.sample_count,
                    evidence.anomaly_rate,
                    json.dumps(dict(evidence.feature_psi), separators=(",", ":")),
                    evidence.maximum_feature_psi,
                    evidence.passed,
                    list(evidence.failed_gates),
                ),
            )
