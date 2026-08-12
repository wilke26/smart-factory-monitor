"""Database infrastructure adapters."""

from smart_factory.infrastructure.database.telemetry_repository import (
    PsycopgTelemetryRepository,
)

__all__ = ["PsycopgTelemetryRepository"]
