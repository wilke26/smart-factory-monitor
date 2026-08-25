from datetime import UTC, datetime
from unittest.mock import DEFAULT, MagicMock, Mock, call

import pytest

from smart_factory.application.ports.telemetry import TelemetryIdentityConflictError
from smart_factory.domain.anomaly import AnomalyFinding, AnomalySeverity
from smart_factory.domain.telemetry import TelemetryReading
from smart_factory.infrastructure.database.telemetry_repository import (
    INSERT_ANOMALY,
    INSERT_TELEMETRY,
    SELECT_RECENT_TELEMETRY,
    SELECT_TELEMETRY_BY_IDENTITY,
    SELECT_TELEMETRY_SINCE,
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


def repository_with_pool(
    *,
    rowcount: int = 1,
    on_availability_change: Mock | None = None,
) -> tuple[PsycopgTelemetryRepository, MagicMock]:
    pool = MagicMock()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.rowcount = rowcount
    repository = PsycopgTelemetryRepository(
        "unused",
        pool=pool,
        on_availability_change=on_availability_change,
    )
    return repository, pool


def test_opens_and_closes_pool() -> None:
    availability = Mock()
    repository, pool = repository_with_pool(on_availability_change=availability)

    repository.open(timeout=7.5)
    repository.close()

    pool.open.assert_called_once_with(wait=True, timeout=7.5)
    pool.close.assert_called_once()
    assert availability.call_args_list == [call(True), call(False)]


def test_reports_unavailable_after_open_failure() -> None:
    availability = Mock()
    repository, pool = repository_with_pool(on_availability_change=availability)
    pool.open.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        repository.open()

    availability.assert_called_once_with(False)


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
    repository, pool = repository_with_pool(rowcount=0)
    measurement = reading()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (
        measurement.temperature_c,
        measurement.vibration_mm_s,
        measurement.power_kw,
        measurement.production_rate,
    )

    assert repository.save(measurement, (finding(),)) is False
    assert cursor.execute.call_args_list[1].args == (
        SELECT_TELEMETRY_BY_IDENTITY,
        (measurement.machine_id, measurement.timestamp),
    )


def test_rejects_same_identity_with_different_measurement() -> None:
    availability = Mock()
    repository, pool = repository_with_pool(
        rowcount=0,
        on_availability_change=availability,
    )
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (95.0, 2.7, 17.3, 44)

    with pytest.raises(TelemetryIdentityConflictError, match="press-01"):
        repository.save(reading(), (finding(),))

    cursor.executemany.assert_not_called()
    availability.assert_called_once_with(True)


def test_runtime_database_failure_changes_readiness_until_next_success() -> None:
    availability = Mock()
    repository, pool = repository_with_pool(on_availability_change=availability)
    pool.connection.side_effect = [RuntimeError("database unavailable"), DEFAULT]

    with pytest.raises(RuntimeError, match="database unavailable"):
        repository.save(reading(), ())

    assert repository.save(reading(), ()) is True
    assert availability.call_args_list == [call(False), call(True)]


def test_loads_recent_readings_for_training() -> None:
    repository, pool = repository_with_pool()
    measurement = reading()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (
            measurement.machine_id,
            measurement.timestamp,
            measurement.temperature_c,
            measurement.vibration_mm_s,
            measurement.power_kw,
            measurement.production_rate,
        )
    ]

    result = repository.load_recent_readings("press-01", 500)

    cursor.execute.assert_called_once_with(SELECT_RECENT_TELEMETRY, ("press-01", 500))
    assert result == [measurement]


def test_loads_only_post_training_readings_for_evaluation() -> None:
    repository, pool = repository_with_pool()
    measurement = reading()
    connection = pool.connection.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (
            measurement.machine_id,
            measurement.timestamp,
            measurement.temperature_c,
            measurement.vibration_mm_s,
            measurement.power_kw,
            measurement.production_rate,
        )
    ]
    trained_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    result = repository.load_readings_since("press-01", trained_at, 1_000)

    cursor.execute.assert_called_once_with(
        SELECT_TELEMETRY_SINCE,
        ("press-01", trained_at, 1_000),
    )
    assert result == [measurement]
