"""Machine-learning adapters for offline training and online inference."""

from smart_factory.infrastructure.ml.isolation_forest import (
    IsolationForestAnomalyDetector,
    IsolationForestTrainer,
)

__all__ = ["IsolationForestAnomalyDetector", "IsolationForestTrainer"]
