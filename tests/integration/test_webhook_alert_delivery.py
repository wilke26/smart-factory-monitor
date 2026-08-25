import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from uuid import UUID

import pytest

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


class RedirectingHandler(BaseHTTPRequestHandler):
    redirected_request_received = False

    def do_POST(self) -> None:
        self.send_response(307)
        self.send_header("Location", "/redirected")
        self.end_headers()

    def do_GET(self) -> None:
        type(self).redirected_request_received = True
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


def test_does_not_follow_webhook_redirects() -> None:
    RedirectingHandler.redirected_request_received = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sink = WebhookAlertSink(
            f"http://127.0.0.1:{server.server_port}/alerts",
            timeout_seconds=2,
        )
        with pytest.raises(HTTPError, match="HTTP Error 307"):
            sink.send(
                AnomalyAlert(
                    event_id=UUID("22222222-2222-2222-2222-222222222222"),
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
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert RedirectingHandler.redirected_request_received is False
