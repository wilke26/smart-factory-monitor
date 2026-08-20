"""Dependency-free Prometheus metrics and HTTP health probes."""

from __future__ import annotations

import json
import threading
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final

_OUTCOMES: Final = (
    "accepted",
    "invalid_payload",
    "invalid_topic",
    "topic_mismatch",
    "identity_conflict",
    "processing_failed",
)


class RuntimeObservability:
    """Keep bounded process metrics and readiness state in memory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mqtt_connected = False
        self._database_ready = False
        self._mqtt_messages: Counter[str] = Counter()
        self._processed_total = 0
        self._inserted_total = 0
        self._anomaly_findings_total = 0
        self._processing_duration_seconds = 0.0

    def set_mqtt_connected(self, connected: bool) -> None:
        with self._lock:
            self._mqtt_connected = connected

    def set_database_ready(self, ready: bool) -> None:
        with self._lock:
            self._database_ready = ready

    def record_mqtt_outcome(self, outcome: str) -> None:
        if outcome not in _OUTCOMES:
            raise ValueError(f"unsupported MQTT outcome: {outcome}")
        with self._lock:
            self._mqtt_messages[outcome] += 1

    def record_processed(
        self,
        *,
        inserted: bool,
        anomaly_count: int,
        duration_seconds: float,
    ) -> None:
        with self._lock:
            self._processed_total += 1
            self._inserted_total += int(inserted)
            self._anomaly_findings_total += anomaly_count
            self._processing_duration_seconds += duration_seconds

    def is_ready(self) -> bool:
        with self._lock:
            return self._mqtt_connected and self._database_ready

    def health_document(self) -> dict[str, object]:
        with self._lock:
            mqtt_connected = self._mqtt_connected
            database_ready = self._database_ready
        return {
            "status": "ready" if mqtt_connected and database_ready else "not_ready",
            "mqtt_connected": mqtt_connected,
            "database_ready": database_ready,
        }

    def render_prometheus(self) -> bytes:
        with self._lock:
            mqtt_connected = self._mqtt_connected
            database_ready = self._database_ready
            messages = {outcome: self._mqtt_messages[outcome] for outcome in _OUTCOMES}
            processed_total = self._processed_total
            inserted_total = self._inserted_total
            anomaly_findings_total = self._anomaly_findings_total
            duration = self._processing_duration_seconds
        lines = [
            "# HELP smart_factory_mqtt_connected Whether the MQTT subscription is active.",
            "# TYPE smart_factory_mqtt_connected gauge",
            f"smart_factory_mqtt_connected {int(mqtt_connected)}",
            "# HELP smart_factory_database_ready Whether the database pool is ready.",
            "# TYPE smart_factory_database_ready gauge",
            f"smart_factory_database_ready {int(database_ready)}",
            "# HELP smart_factory_mqtt_messages_total MQTT messages by processing outcome.",
            "# TYPE smart_factory_mqtt_messages_total counter",
            *(
                f'smart_factory_mqtt_messages_total{{outcome="{outcome}"}} {messages[outcome]}'
                for outcome in _OUTCOMES
            ),
            "# HELP smart_factory_telemetry_processed_total Successfully processed messages.",
            "# TYPE smart_factory_telemetry_processed_total counter",
            f"smart_factory_telemetry_processed_total {processed_total}",
            "# HELP smart_factory_telemetry_inserted_total Newly inserted telemetry readings.",
            "# TYPE smart_factory_telemetry_inserted_total counter",
            f"smart_factory_telemetry_inserted_total {inserted_total}",
            "# HELP smart_factory_anomaly_findings_total Persisted anomaly findings observed.",
            "# TYPE smart_factory_anomaly_findings_total counter",
            f"smart_factory_anomaly_findings_total {anomaly_findings_total}",
            "# HELP smart_factory_processing_duration_seconds Processing time sum and count.",
            "# TYPE smart_factory_processing_duration_seconds summary",
            f"smart_factory_processing_duration_seconds_sum {duration:.9f}",
            f"smart_factory_processing_duration_seconds_count {processed_total}",
        ]
        return ("\n".join(lines) + "\n").encode("utf-8")


class MonitoringServer:
    """Expose liveness, readiness, and Prometheus metrics on a small HTTP server."""

    def __init__(self, observability: RuntimeObservability, host: str, port: int) -> None:
        handler = self._handler(observability)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="monitoring-http",
            daemon=True,
        )

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def __enter__(self) -> MonitoringServer:
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @staticmethod
    def _handler(observability: RuntimeObservability) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/healthz":
                    self._respond_json(HTTPStatus.OK, {"status": "alive"})
                    return
                if self.path == "/readyz":
                    status = (
                        HTTPStatus.OK
                        if observability.is_ready()
                        else HTTPStatus.SERVICE_UNAVAILABLE
                    )
                    self._respond_json(status, observability.health_document())
                    return
                if self.path == "/metrics":
                    payload = observability.render_prometheus()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self._respond_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

            def _respond_json(self, status: HTTPStatus, document: dict[str, object]) -> None:
                payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        return Handler
