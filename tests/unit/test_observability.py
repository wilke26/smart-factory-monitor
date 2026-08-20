import json
from io import BytesIO
from typing import Any, cast
from unittest.mock import Mock

from smart_factory.observability import MonitoringServer, RuntimeObservability


def request(observability: RuntimeObservability, path: str) -> tuple[int, bytes]:
    handler_type = MonitoringServer._handler(observability)
    handler = cast(Any, object.__new__(handler_type))
    handler.path = path
    handler.wfile = BytesIO()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()

    handler.do_GET()

    return handler.send_response.call_args.args[0], handler.wfile.getvalue()


def test_metrics_are_bounded_aggregates() -> None:
    observability = RuntimeObservability()
    observability.set_database_ready(True)
    observability.set_mqtt_connected(True)
    observability.record_mqtt_outcome("accepted")
    observability.record_processed(
        inserted=True,
        anomaly_count=2,
        duration_seconds=0.125,
    )

    metrics = observability.render_prometheus().decode("utf-8")

    assert observability.is_ready()
    assert 'smart_factory_mqtt_messages_total{outcome="accepted"} 1' in metrics
    assert "smart_factory_telemetry_inserted_total 1" in metrics
    assert "smart_factory_anomaly_findings_total 2" in metrics
    assert "smart_factory_processing_duration_seconds_sum 0.125000000" in metrics


def test_monitoring_endpoints_reflect_readiness() -> None:
    observability = RuntimeObservability()

    status, payload = request(observability, "/readyz")
    assert status == 503
    assert json.loads(payload)["status"] == "not_ready"

    observability.set_database_ready(True)
    observability.set_mqtt_connected(True)
    assert request(observability, "/healthz")[0] == 200
    assert request(observability, "/readyz")[0] == 200
    assert request(observability, "/metrics")[0] == 200
    assert request(observability, "/missing")[0] == 404
