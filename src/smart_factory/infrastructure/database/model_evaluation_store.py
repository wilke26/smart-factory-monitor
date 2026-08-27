"""Psycopg adapter for durable model-evaluation evidence."""

from __future__ import annotations

import json

from smart_factory.domain.model_evaluation import ModelEvaluationEvidence
from smart_factory.infrastructure.database._pool import ConnectionPoolLike, create_pool

INSERT_MODEL_EVALUATION = """
INSERT INTO model_evaluation_runs (
    evaluation_id,
    evaluated_at,
    model_id,
    artifact_sha256,
    machine_id,
    training_window_end,
    sample_count,
    anomaly_rate,
    feature_psi,
    maximum_feature_psi,
    passed,
    failed_gates
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
"""

HAS_PASSED_MODEL_EVALUATION = """
SELECT EXISTS (
    SELECT 1
    FROM model_evaluation_runs
    WHERE machine_id = %s
      AND model_id = %s
      AND artifact_sha256 = %s
      AND passed
)
"""


def _create_pool(database_url: str, *, min_size: int, max_size: int) -> ConnectionPoolLike:
    return create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        name="model-evaluation-pool",
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
                    evidence.artifact_sha256,
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

    def has_passed(
        self,
        *,
        machine_id: str,
        model_id: str,
        artifact_sha256: str,
    ) -> bool:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                HAS_PASSED_MODEL_EVALUATION,
                (machine_id, model_id, artifact_sha256),
            )
            row = cursor.fetchone()
        return bool(row and row[0])
