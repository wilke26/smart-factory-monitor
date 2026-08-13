"""Deterministic and explainable telemetry anomaly rules."""

from dataclasses import dataclass

from smart_factory.domain.anomaly import AnomalyFinding, AnomalySeverity
from smart_factory.domain.telemetry import TelemetryReading


@dataclass(frozen=True, slots=True)
class AnomalyThresholds:
    """Business thresholds, kept explicit and configurable."""

    maximum_temperature_c: float = 90.0
    maximum_vibration_mm_s: float = 7.0
    maximum_power_kw: float = 30.0
    minimum_production_rate: int = 25


class RuleBasedAnomalyDetector:
    """Evaluate independent rules and return every violated condition."""

    def __init__(self, thresholds: AnomalyThresholds | None = None) -> None:
        self._thresholds = thresholds or AnomalyThresholds()

    def evaluate(self, reading: TelemetryReading) -> tuple[AnomalyFinding, ...]:
        findings: list[AnomalyFinding] = []
        self._append_above_maximum(
            findings,
            rule_id="temperature-high",
            severity=AnomalySeverity.HIGH,
            metric="temperature_c",
            observed=float(reading.temperature_c),
            threshold=self._thresholds.maximum_temperature_c,
        )
        self._append_above_maximum(
            findings,
            rule_id="vibration-high",
            severity=AnomalySeverity.HIGH,
            metric="vibration_mm_s",
            observed=float(reading.vibration_mm_s),
            threshold=self._thresholds.maximum_vibration_mm_s,
        )
        self._append_above_maximum(
            findings,
            rule_id="power-high",
            severity=AnomalySeverity.HIGH,
            metric="power_kw",
            observed=float(reading.power_kw),
            threshold=self._thresholds.maximum_power_kw,
        )
        if reading.production_rate < self._thresholds.minimum_production_rate:
            threshold = float(self._thresholds.minimum_production_rate)
            findings.append(
                AnomalyFinding(
                    rule_id="production-rate-low",
                    severity=AnomalySeverity.MEDIUM,
                    metric="production_rate",
                    observed_value=float(reading.production_rate),
                    threshold=threshold,
                    comparison="<",
                    message=(
                        f"production_rate={reading.production_rate} is below minimum {threshold:g}"
                    ),
                )
            )
        return tuple(findings)

    @staticmethod
    def _append_above_maximum(
        findings: list[AnomalyFinding],
        *,
        rule_id: str,
        severity: AnomalySeverity,
        metric: str,
        observed: float,
        threshold: float,
    ) -> None:
        if observed > threshold:
            findings.append(
                AnomalyFinding(
                    rule_id=rule_id,
                    severity=severity,
                    metric=metric,
                    observed_value=observed,
                    threshold=threshold,
                    comparison=">",
                    message=f"{metric}={observed:g} exceeds maximum {threshold:g}",
                )
            )
