"""Technology-neutral observability ports for application processing."""

from typing import Protocol


class TelemetryProcessingObserver(Protocol):
    """Receive aggregate processing results without exposing a metrics backend."""

    def record_processed(
        self,
        *,
        inserted: bool,
        anomaly_count: int,
        duration_seconds: float,
    ) -> None: ...
