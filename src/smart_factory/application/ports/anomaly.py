"""Ports for anomaly detectors used by the telemetry use case."""

from typing import Protocol

from smart_factory.domain.anomaly import AnomalyFinding
from smart_factory.domain.telemetry import TelemetryReading


class AnomalyDetector(Protocol):
    """Evaluate one validated reading without exposing detector technology."""

    def evaluate(self, reading: TelemetryReading) -> tuple[AnomalyFinding, ...]: ...
