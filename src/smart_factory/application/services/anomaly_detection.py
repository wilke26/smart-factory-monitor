"""Composition of independent anomaly detectors."""

from smart_factory.application.ports.anomaly import AnomalyDetector
from smart_factory.domain.anomaly import AnomalyFinding
from smart_factory.domain.telemetry import TelemetryReading


class CompositeAnomalyDetector:
    """Run every configured detector and retain all findings in stable order."""

    def __init__(self, detectors: tuple[AnomalyDetector, ...]) -> None:
        if not detectors:
            raise ValueError("at least one anomaly detector is required")
        self._detectors = detectors

    def evaluate(self, reading: TelemetryReading) -> tuple[AnomalyFinding, ...]:
        return tuple(
            finding for detector in self._detectors for finding in detector.evaluate(reading)
        )
