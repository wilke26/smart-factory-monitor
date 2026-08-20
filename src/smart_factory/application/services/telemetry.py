"""Use case for validated telemetry readings."""

import logging
from collections.abc import Callable
from time import monotonic

from smart_factory.application.ports.anomaly import AnomalyDetector
from smart_factory.application.ports.observability import TelemetryProcessingObserver
from smart_factory.application.ports.telemetry import TelemetryRepository
from smart_factory.domain.anomaly import AnomalyFinding
from smart_factory.domain.telemetry import TelemetryReading


class TelemetryApplicationService:
    """Detect and persist valid readings without transport or database details."""

    def __init__(
        self,
        *,
        repository: TelemetryRepository,
        anomaly_detector: AnomalyDetector,
        on_processed: Callable[[TelemetryReading], None] | None = None,
        observer: TelemetryProcessingObserver | None = None,
        clock: Callable[[], float] = monotonic,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._anomaly_detector = anomaly_detector
        self._on_processed = on_processed
        self._observer = observer
        self._clock = clock
        self._logger = logger or logging.getLogger(__name__)
        self._processed_count = 0

    @property
    def processed_count(self) -> int:
        return self._processed_count

    def process(self, reading: TelemetryReading) -> None:
        """Detect anomalies and atomically persist the complete processing result."""
        started_at = self._clock()
        findings = self._anomaly_detector.evaluate(reading)
        inserted = self._repository.save(reading, findings)
        self._processed_count += 1
        if self._observer is not None:
            self._observer.record_processed(
                inserted=inserted,
                anomaly_count=len(findings),
                duration_seconds=self._clock() - started_at,
            )
        if self._on_processed is not None:
            self._on_processed(reading)
        self._logger.info(
            "telemetry_processed",
            extra={
                "machine_id": reading.machine_id,
                "reading_timestamp": reading.timestamp.isoformat(),
                "processed_count": self._processed_count,
                "inserted": inserted,
                "anomaly_count": len(findings),
            },
        )
        self._log_findings(reading, findings)

    def _log_findings(
        self,
        reading: TelemetryReading,
        findings: tuple[AnomalyFinding, ...],
    ) -> None:
        for finding in findings:
            self._logger.warning(
                "anomaly_detected",
                extra={
                    "machine_id": reading.machine_id,
                    "reading_timestamp": reading.timestamp.isoformat(),
                    "rule_id": finding.rule_id,
                    "severity": finding.severity.value,
                    "metric": finding.metric,
                    "observed_value": finding.observed_value,
                    "threshold": finding.threshold,
                    "comparison": finding.comparison,
                },
            )
