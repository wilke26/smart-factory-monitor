from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from smart_factory.domain.model_evaluation import ModelEvaluationEvidence


def evidence(**updates: object) -> ModelEvaluationEvidence:
    values: dict[str, object] = {
        "evaluation_id": UUID("11111111-1111-1111-1111-111111111111"),
        "evaluated_at": datetime(2026, 8, 26, tzinfo=UTC),
        "model_id": "isolation-forest-2026-08-25",
        "machine_id": "press-01",
        "training_window_end": datetime(2026, 8, 25, tzinfo=UTC),
        "sample_count": 120,
        "anomaly_rate": 0.05,
        "feature_psi": (("temperature_c", 0.1), ("power_kw", 0.2)),
        "maximum_feature_psi": 0.2,
        "passed": True,
        "failed_gates": (),
    }
    values.update(updates)
    return ModelEvaluationEvidence.model_validate(values)


def test_accepts_consistent_immutable_evaluation_evidence() -> None:
    record = evidence()

    assert record.machine_id == "press-01"
    assert record.maximum_feature_psi == 0.2
    with pytest.raises(ValidationError):
        record.sample_count = 0


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"feature_psi": (("temperature_c", 0.1),) * 2}, "feature names"),
        ({"maximum_feature_psi": 0.1}, "must match"),
        ({"passed": False}, "must agree"),
        (
            {"training_window_end": datetime(2026, 8, 26, tzinfo=UTC) + timedelta(seconds=1)},
            "must not be after",
        ),
    ],
)
def test_rejects_inconsistent_evaluation_evidence(updates: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        evidence(**updates)


def test_rejects_naive_evaluation_timestamp() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        evidence(evaluated_at=datetime(2026, 8, 26))
