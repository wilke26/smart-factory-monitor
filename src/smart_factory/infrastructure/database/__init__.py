"""Database infrastructure adapters."""

from smart_factory.infrastructure.database.alert_outbox import PsycopgAlertOutbox
from smart_factory.infrastructure.database.telemetry_repository import (
    PsycopgTelemetryRepository,
)

__all__ = [
    "PsycopgAlertOutbox",
    "PsycopgTelemetryRepository",
]
