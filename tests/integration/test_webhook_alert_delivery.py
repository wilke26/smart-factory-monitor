import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

from smart_factory.domain.alert import AnomalyAlert
from smart_factory.domain.anomaly import AnomalySeverity
from smart_factory.infrastructure.alerts.webhook import WebhookAlertSink


class RecordingHandler(BaseHTTPRequestHandler):
    payload: bytes = b""
    idempotency_key: str | None = None

    def do_POST(self) -> None:
        type(self).payload = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).idempotency_key = self.headers["Idempotency-Key"]
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_delivers_real_http_request_with_stable_event_identity() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    event_id = UUID("11111111-1111-1111-1111-111111111111")
    alert = AnomalyAlert(
        event_id=event_id,
        machine_id="press-01",
        recorded_at=datetime(2026, 8, 25, tzinfo=UTC),
        rule_id="temperature-high",
        severity=AnomalySeverity.HIGH,
        metric="temperature_c",
        observed_value=95.0,
        threshold=90.0,
        comparison=">",
        message="temperature exceeds maximum",
    )
    try:
        WebhookAlertSink(
            f"http://127.0.0.1:{server.server_port}/alerts",
            timeout_seconds=2,
        ).send(alert)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert RecordingHandler.idempotency_key == str(event_id)
    assert json.loads(RecordingHandler.payload) == alert.model_dump(mode="json")
