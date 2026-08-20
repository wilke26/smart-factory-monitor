from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from smart_factory.application.services.telemetry import TelemetryApplicationService
from smart_factory.domain.services.anomaly_detection import RuleBasedAnomalyDetector
from smart_factory.domain.telemetry import TelemetryReading


def reading() -> TelemetryReading:
    return TelemetryReading(
        machine_id="press-01",
        timestamp=datetime(2026, 8, 12, tzinfo=UTC),
        temperature_c=68.4,
        vibration_mm_s=2.7,
        power_kw=17.3,
        production_rate=44,
    )


def test_processes_reading_without_transport_details() -> None:
    callback = Mock()
    logger = Mock()
    repository = Mock()
    repository.save.return_value = True
    service = TelemetryApplicationService(
        repository=repository,
        anomaly_detector=RuleBasedAnomalyDetector(),
        on_processed=callback,
        logger=logger,
    )

    service.process(reading())

    callback.assert_called_once_with(reading())
    repository.save.assert_called_once_with(reading(), ())
    assert service.processed_count == 1
    logger.info.assert_called_once()


def test_callback_is_optional() -> None:
    service = TelemetryApplicationService(
        repository=Mock(), anomaly_detector=RuleBasedAnomalyDetector(), logger=Mock()
    )

    service.process(reading())

    assert service.processed_count == 1


def test_failed_persistence_does_not_mark_reading_processed() -> None:
    repository = Mock()
    repository.save.side_effect = RuntimeError("database unavailable")
    callback = Mock()
    service = TelemetryApplicationService(
        repository=repository,
        anomaly_detector=RuleBasedAnomalyDetector(),
        on_processed=callback,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.process(reading())

    assert service.processed_count == 0
    callback.assert_not_called()


def test_detected_findings_are_persisted_and_logged() -> None:
    repository = Mock()
    repository.save.return_value = True
    logger = Mock()
    service = TelemetryApplicationService(
        repository=repository,
        anomaly_detector=RuleBasedAnomalyDetector(),
        logger=logger,
    )
    anomalous = reading().model_copy(update={"temperature_c": 95.0})

    service.process(anomalous)

    findings = repository.save.call_args.args[1]
    assert [finding.rule_id for finding in findings] == ["temperature-high"]
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[0] == "anomaly_detected"


def test_reports_processing_metrics_after_persistence() -> None:
    repository = Mock()
    repository.save.return_value = False
    observer = Mock()
    clock = Mock(side_effect=[10.0, 10.25])
    service = TelemetryApplicationService(
        repository=repository,
        anomaly_detector=RuleBasedAnomalyDetector(),
        observer=observer,
        clock=clock,
        logger=Mock(),
    )

    service.process(reading())

    observer.record_processed.assert_called_once_with(
        inserted=False,
        anomaly_count=0,
        duration_seconds=0.25,
    )
