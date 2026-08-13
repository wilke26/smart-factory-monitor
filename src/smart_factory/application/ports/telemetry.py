"""Inbound telemetry port."""

from typing import Protocol

from smart_factory.domain.anomaly import AnomalyFinding
from smart_factory.domain.telemetry import TelemetryReading


class TelemetryHandler(Protocol):
    """Something that processes already validated telemetry."""

    def process(self, reading: TelemetryReading) -> None:
        """Process a reading without transport-specific arguments."""
        ...


class TelemetryRepository(Protocol):
    """Outbound port for durable telemetry storage."""

    def save(
        self,
        reading: TelemetryReading,
        findings: tuple[AnomalyFinding, ...],
    ) -> bool:
        """Atomically persist a reading and its findings; report a new reading."""
        ...
