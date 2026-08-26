"""Outbound port for durable model-evaluation evidence."""

from typing import Protocol

from smart_factory.domain.model_evaluation import ModelEvaluationEvidence


class ModelEvaluationStore(Protocol):
    """Persist one immutable evaluation result."""

    def save(self, evidence: ModelEvaluationEvidence) -> None: ...
