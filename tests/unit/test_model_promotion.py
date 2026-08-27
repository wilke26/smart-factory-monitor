from pathlib import Path
from unittest.mock import Mock, call

import pytest

from smart_factory.application.services.model_promotion import (
    ModelPromotionError,
    ModelPromotionService,
    PromotionCandidate,
)


def candidates() -> tuple[PromotionCandidate, ...]:
    return (
        PromotionCandidate("press-01", "model-1", "a" * 64, Path("/candidates/one")),
        PromotionCandidate("press-02", "model-2", "b" * 64, Path("/candidates/two")),
    )


def test_publishes_complete_batch_only_after_every_candidate_passed() -> None:
    approvals = Mock()
    approvals.has_passed.return_value = True
    registry = Mock()
    service = ModelPromotionService(approvals, registry)
    batch = candidates()

    result = service.promote(batch)

    assert result is registry.publish.return_value
    assert approvals.has_passed.call_args_list == [
        call(machine_id="press-01", model_id="model-1", artifact_sha256="a" * 64),
        call(machine_id="press-02", model_id="model-2", artifact_sha256="b" * 64),
    ]
    registry.publish.assert_called_once_with(batch)


def test_rejects_entire_batch_when_exact_artifact_has_no_passed_evaluation() -> None:
    approvals = Mock()
    approvals.has_passed.side_effect = [True, False]
    registry = Mock()

    with pytest.raises(ModelPromotionError, match="press-02"):
        ModelPromotionService(approvals, registry).promote(candidates())

    registry.publish.assert_not_called()
