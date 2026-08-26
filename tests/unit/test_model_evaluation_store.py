import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

from smart_factory.domain.model_evaluation import ModelEvaluationEvidence
from smart_factory.infrastructure.database.model_evaluation_store import (
    INSERT_MODEL_EVALUATION,
    PsycopgModelEvaluationStore,
)


def store_with_pool() -> tuple[PsycopgModelEvaluationStore, MagicMock, MagicMock]:
    pool = MagicMock()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    return PsycopgModelEvaluationStore("unused", pool=pool), pool, cursor


def evidence() -> ModelEvaluationEvidence:
    return ModelEvaluationEvidence(
        evaluation_id=UUID("11111111-1111-1111-1111-111111111111"),
        evaluated_at=datetime(2026, 8, 26, tzinfo=UTC),
        model_id="model-1",
        machine_id="press-01",
        training_window_end=datetime(2026, 8, 25, tzinfo=UTC),
        sample_count=120,
        anomaly_rate=0.05,
        feature_psi=(("temperature_c", 0.1), ("power_kw", 0.2)),
        maximum_feature_psi=0.2,
        passed=False,
        failed_gates=("maximum_feature_psi",),
    )


def test_opens_and_closes_bounded_pool() -> None:
    store, pool, _ = store_with_pool()

    store.open(timeout=7)
    store.close()

    pool.open.assert_called_once_with(wait=True, timeout=7)
    pool.close.assert_called_once()


def test_persists_complete_evaluation_evidence() -> None:
    store, _, cursor = store_with_pool()
    record = evidence()

    store.save(record)

    query, params = cursor.execute.call_args.args
    assert query == INSERT_MODEL_EVALUATION
    assert params[:7] == (
        record.evaluation_id,
        record.evaluated_at,
        "model-1",
        "press-01",
        record.training_window_end,
        120,
        0.05,
    )
    assert json.loads(params[7]) == {"temperature_c": 0.1, "power_kw": 0.2}
    assert params[8:] == (0.2, False, ["maximum_feature_psi"])
