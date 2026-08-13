from datetime import UTC, datetime

import pytest

from smart_factory.domain.anomaly import AnomalySeverity
from smart_factory.domain.services.anomaly_detection import (
    AnomalyThresholds,
    RuleBasedAnomalyDetector,
)
from smart_factory.domain.telemetry import TelemetryReading


def reading(**overrides: float | int) -> TelemetryReading:
    values: dict[str, object] = {
        "machine_id": "press-01",
        "timestamp": datetime(2026, 8, 12, tzinfo=UTC),
        "temperature_c": 68.0,
        "vibration_mm_s": 2.5,
        "power_kw": 17.0,
        "production_rate": 44,
    }
    values.update(overrides)
    return TelemetryReading(**values)  # type: ignore[arg-type]


def test_normal_reading_has_no_findings() -> None:
    assert RuleBasedAnomalyDetector().evaluate(reading()) == ()


@pytest.mark.parametrize(
    ("overrides", "rule_id", "severity"),
    [
        ({"temperature_c": 90.1}, "temperature-high", AnomalySeverity.HIGH),
        ({"vibration_mm_s": 7.1}, "vibration-high", AnomalySeverity.HIGH),
        ({"power_kw": 30.1}, "power-high", AnomalySeverity.HIGH),
        ({"production_rate": 24}, "production-rate-low", AnomalySeverity.MEDIUM),
    ],
)
def test_each_rule_is_explainable(
    overrides: dict[str, float | int], rule_id: str, severity: AnomalySeverity
) -> None:
    findings = RuleBasedAnomalyDetector().evaluate(reading(**overrides))

    assert len(findings) == 1
    assert findings[0].rule_id == rule_id
    assert findings[0].severity is severity
    assert findings[0].metric in findings[0].message


def test_exact_thresholds_are_not_anomalous() -> None:
    at_boundaries = reading(
        temperature_c=90,
        vibration_mm_s=7,
        power_kw=30,
        production_rate=25,
    )

    assert RuleBasedAnomalyDetector().evaluate(at_boundaries) == ()


def test_all_violated_rules_are_returned_in_stable_order() -> None:
    findings = RuleBasedAnomalyDetector().evaluate(
        reading(temperature_c=100, vibration_mm_s=9, power_kw=35, production_rate=10)
    )

    assert [finding.rule_id for finding in findings] == [
        "temperature-high",
        "vibration-high",
        "power-high",
        "production-rate-low",
    ]


def test_custom_thresholds_are_applied() -> None:
    detector = RuleBasedAnomalyDetector(
        AnomalyThresholds(maximum_temperature_c=70, minimum_production_rate=40)
    )

    assert [finding.rule_id for finding in detector.evaluate(reading(temperature_c=71))] == [
        "temperature-high"
    ]
