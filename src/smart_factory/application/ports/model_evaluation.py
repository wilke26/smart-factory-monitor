"""Outbound port for durable model-evaluation evidence."""

from typing import Protocol

from smart_factory.domain.model_evaluation import ModelEvaluationEvidence


class ModelEvaluationStore(Protocol):
    """Persist one immutable evaluation result."""

    def save(self, evidence: ModelEvaluationEvidence) -> None: ...


class ModelApprovalReader(Protocol):
    """Check promotion eligibility for one exact evaluated artifact."""

    def has_passed(
        self,
        *,
        machine_id: str,
        model_id: str,
        artifact_sha256: str,
    ) -> bool: ...
