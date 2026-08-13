from datetime import UTC, datetime
from unittest.mock import MagicMock

from smart_factory.domain.anomaly import AnomalyFinding, AnomalySeverity
from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.database.telemetry_repository import (
    INSERT_ANOMALY,
    INSERT_TELEMETRY,
    PsycopgTelemetryRepository,
)


def reading() -> TelemetryReading:
    return TelemetryReading(
        machine_id="press-01",
        timestamp=datetime(2026, 8, 12, 12, 30, tzinfo=UTC),
        temperature_c=68.4,
        vibration_mm_s=2.7,
        power_kw=17.3,
        production_rate=44,
    )


def finding() -> AnomalyFinding:
    return AnomalyFinding(
        rule_id="temperature-high",
        severity=AnomalySeverity.HIGH,
        metric="temperature_c",
        observed_value=95.0,
        threshold=90.0,
        comparison=">",
        message="temperature_c=95 exceeds maximum 90",
    )


def repository_with_pool(*, rowcount: int = 1) -> tuple[PsycopgTelemetryRepository, MagicMock]:
    pool = MagicMock()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.rowcount = rowcount
    repository = PsycopgTelemetryRepository("unused", pool=pool)
    return repository, pool


def test_opens_and_closes_pool() -> None:
    repository, pool = repository_with_pool()

    repository.open(timeout=7.5)
    repository.close()

    pool.open.assert_called_once_with(wait=True, timeout=7.5)
    pool.close.assert_called_once()


def test_saves_all_contract_fields_in_one_parameterized_statement() -> None:
    repository, pool = repository_with_pool()
    measurement = reading()

    inserted = repository.save(measurement, ())

    assert inserted is True
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.execute.assert_called_once_with(
        INSERT_TELEMETRY,
        (
            "press-01",
            measurement.timestamp,
            68.4,
            2.7,
            17.3,
            44,
        ),
    )
    cursor.executemany.assert_not_called()


def test_saves_findings_in_same_connection_transaction() -> None:
    repository, pool = repository_with_pool()
    measurement = reading()
    anomaly = finding()

    repository.save(measurement, (anomaly,))

    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.executemany.assert_called_once_with(
        INSERT_ANOMALY,
        [
            (
                "press-01",
                measurement.timestamp,
                "temperature-high",
                "high",
                "temperature_c",
                95.0,
                90.0,
                ">",
                "temperature_c=95 exceeds maximum 90",
            )
        ],
    )


def test_duplicate_is_idempotent() -> None:
    repository, _ = repository_with_pool(rowcount=0)

    assert repository.save(reading(), (finding(),)) is False
