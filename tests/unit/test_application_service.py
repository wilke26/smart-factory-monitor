from datetime import UTC, datetime
from unittest.mock import Mock

from smart_factory.application.services.telemetry import TelemetryApplicationService
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
    service = TelemetryApplicationService(on_processed=callback, logger=logger)

    service.process(reading())

    callback.assert_called_once_with(reading())
    assert service.processed_count == 1
    logger.info.assert_called_once()


def test_callback_is_optional() -> None:
    service = TelemetryApplicationService(logger=Mock())

    service.process(reading())

    assert service.processed_count == 1
