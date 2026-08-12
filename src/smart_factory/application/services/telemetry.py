"""Use case for validated telemetry readings."""

import logging
from collections.abc import Callable

from smart_factory.application.ports.telemetry import TelemetryRepository
from smart_factory.domain.telemetry import TelemetryReading


class TelemetryApplicationService:
    """Process valid readings while remaining unaware of MQTT and JSON."""

    def __init__(
        self,
        *,
        repository: TelemetryRepository,
        on_processed: Callable[[TelemetryReading], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._on_processed = on_processed
        self._logger = logger or logging.getLogger(__name__)
        self._processed_count = 0

    @property
    def processed_count(self) -> int:
        return self._processed_count

    def process(self, reading: TelemetryReading) -> None:
        """Execute the current in-memory processing use case."""
        inserted = self._repository.save(reading)
        self._processed_count += 1
        if self._on_processed is not None:
            self._on_processed(reading)
        self._logger.info(
            "telemetry_processed",
            extra={
                "machine_id": reading.machine_id,
                "reading_timestamp": reading.timestamp.isoformat(),
                "processed_count": self._processed_count,
                "inserted": inserted,
            },
        )
