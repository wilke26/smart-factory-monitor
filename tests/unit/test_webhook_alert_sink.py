import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from smart_factory.domain.alert import AnomalyAlert
from smart_factory.domain.anomaly import AnomalySeverity
from smart_factory.infrastructure.alerts.webhook import WebhookAlertSink


def alert() -> AnomalyAlert:
    return AnomalyAlert(
        event_id=UUID("11111111-1111-1111-1111-111111111111"),
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


def response(status: int) -> MagicMock:
    result = MagicMock()
    result.__enter__.return_value.getcode.return_value = status
    return result


def test_posts_json_with_authentication_and_idempotency_key() -> None:
    opener = Mock(return_value=response(204))
    sink = WebhookAlertSink(
        "https://alerts.example.test/events",
        timeout_seconds=5,
        bearer_token="secret",
        opener=opener,
    )

    sink.send(alert())

    request = opener.call_args.args[0]
    assert request.full_url == "https://alerts.example.test/events"
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer secret"
    assert request.get_header("Idempotency-key") == str(alert().event_id)
    assert json.loads(request.data) == alert().model_dump(mode="json")
    assert opener.call_args.kwargs == {"timeout": 5}


def test_rejects_non_success_response() -> None:
    sink = WebhookAlertSink(
        "https://alerts.example.test/events",
        timeout_seconds=5,
        opener=Mock(return_value=response(500)),
    )

    with pytest.raises(OSError, match="HTTP 500"):
        sink.send(alert())
