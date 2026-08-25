"""Ports for durable, at-least-once anomaly alert delivery."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from smart_factory.domain.alert import AnomalyAlert


@dataclass(frozen=True, slots=True)
class ClaimedAlert:
    """An outbox alert leased to one dispatcher attempt."""

    alert: AnomalyAlert
    lease_token: UUID
    attempt_number: int


class AlertLeaseLostError(RuntimeError):
    """The dispatcher no longer owns the claimed outbox row."""


class AlertOutbox(Protocol):
    """Durable source and delivery-state store for anomaly alerts."""

    def claim(self, *, limit: int, lease_seconds: int) -> tuple[ClaimedAlert, ...]: ...

    def mark_delivered(self, claimed: ClaimedAlert) -> None: ...

    def reschedule(self, claimed: ClaimedAlert, *, delay_seconds: float, error: str) -> None: ...


class AlertSink(Protocol):
    """External alert destination independent of the application service."""

    def send(self, alert: AnomalyAlert) -> None: ...
