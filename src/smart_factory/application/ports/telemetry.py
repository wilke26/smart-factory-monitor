"""Inbound telemetry port."""

from typing import Protocol

from smart_factory.domain.telemetry import TelemetryReading


class TelemetryHandler(Protocol):
    """Something that processes already validated telemetry."""

    def process(self, reading: TelemetryReading) -> None:
        """Process a reading without transport-specific arguments."""
        ...
