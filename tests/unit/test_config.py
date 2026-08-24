import pytest

from smart_factory.config import MlSettings, Settings


def test_defaults_publish_to_v01_acceptance_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MQTT_HOST",
        "MQTT_PORT",
        "MQTT_QOS",
        "MQTT_KEEPALIVE",
        "MQTT_CLIENT_ID",
        "MQTT_CONSUMER_CLIENT_ID",
        "MQTT_TOPIC_FILTER",
        "MQTT_SESSION_EXPIRY_SECONDS",
        "MQTT_RECEIVE_MAXIMUM",
        "FACTORY_AREA",
        "MACHINE_ID",
        "PUBLISH_INTERVAL_SECONDS",
        "SIMULATOR_SEED",
        "LOG_LEVEL",
        "DATABASE_URL",
        "DATABASE_POOL_MIN_SIZE",
        "DATABASE_POOL_MAX_SIZE",
        "DATABASE_CONNECT_TIMEOUT_SECONDS",
        "ANOMALY_MAX_TEMPERATURE_C",
        "ANOMALY_MAX_VIBRATION_MM_S",
        "ANOMALY_MAX_POWER_KW",
        "ANOMALY_MIN_PRODUCTION_RATE",
        "MONITORING_HOST",
        "MONITORING_PORT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.topic == "factory/hall-a/press-01/telemetry"
    assert settings.mqtt_host == "localhost"
    assert settings.mqtt_qos == 1
    assert settings.mqtt_consumer_client_id == "smart-factory-consumer"
    assert settings.mqtt_topic_filter == "factory/+/+/telemetry"
    assert settings.mqtt_session_expiry_seconds == 86_400
    assert settings.mqtt_receive_maximum == 20
    assert settings.database_pool_min_size == 1
    assert settings.database_pool_max_size == 4
    assert settings.database_url.endswith("@localhost:5432/smart_factory")
    assert settings.maximum_temperature_c == 90
    assert settings.maximum_vibration_mm_s == 7
    assert settings.maximum_power_kw == 30
    assert settings.minimum_production_rate == 25
    assert settings.monitoring_host == "0.0.0.0"
    assert settings.monitoring_port == 8000


def test_reads_optional_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMULATOR_SEED", "42")

    assert Settings.from_env().simulator_seed == 42


def test_rejects_non_integer_seed_with_setting_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMULATOR_SEED", "not-an-integer")

    with pytest.raises(ValueError, match="SIMULATOR_SEED must be an integer"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MQTT_QOS", "3"),
        ("MQTT_PORT", "0"),
        ("MQTT_SESSION_EXPIRY_SECONDS", "0"),
        ("MQTT_RECEIVE_MAXIMUM", "65536"),
        ("MONITORING_PORT", "0"),
    ],
)
def test_rejects_out_of_range_integer_settings(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        Settings.from_env()


def test_rejects_non_positive_publish_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLISH_INTERVAL_SECONDS", "0")

    with pytest.raises(ValueError):
        Settings.from_env()


def test_rejects_empty_topic_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_TOPIC_FILTER", " ")

    with pytest.raises(ValueError, match="must not be empty"):
        Settings.from_env()


def test_rejects_invalid_database_pool_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_POOL_MIN_SIZE", "5")
    monkeypatch.setenv("DATABASE_POOL_MAX_SIZE", "4")

    with pytest.raises(ValueError, match="must not exceed"):
        Settings.from_env()


def test_rejects_non_positive_database_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="greater than zero"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ANOMALY_MAX_TEMPERATURE_C", "nan"),
        ("ANOMALY_MAX_VIBRATION_MM_S", "101"),
        ("ANOMALY_MAX_POWER_KW", "-1"),
        ("ANOMALY_MIN_PRODUCTION_RATE", "10001"),
    ],
)
def test_rejects_thresholds_outside_contract_bounds(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="must be between"):
        Settings.from_env()


def test_ml_defaults_to_explicitly_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ML_ANOMALY_DETECTION_ENABLED",
        "ML_MODEL_DIRECTORY",
        "ML_MACHINE_IDS",
        "ML_MACHINE_ID",
        "ML_CONTAMINATION",
        "ML_MINIMUM_TRAINING_SAMPLES",
        "ML_TRAINING_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = MlSettings.from_env()

    assert settings.enabled is False
    assert settings.contamination == 0.05
    assert settings.model_directory == "/models"
    assert settings.machine_ids == ("press-01",)
    assert settings.minimum_training_samples == 100
    assert settings.training_limit == 10_000


@pytest.mark.parametrize("value", ["maybe", "enabled"])
def test_rejects_invalid_ml_boolean(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ML_ANOMALY_DETECTION_ENABLED", value)

    with pytest.raises(ValueError, match="must be a boolean"):
        MlSettings.from_env()


def test_rejects_training_limit_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ML_MINIMUM_TRAINING_SAMPLES", "200")
    monkeypatch.setenv("ML_TRAINING_LIMIT", "100")

    with pytest.raises(ValueError, match="must not be below"):
        MlSettings.from_env()


def test_parses_unique_machine_registry_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ML_MACHINE_IDS", "press-01, press-02,press-01")

    assert MlSettings.from_env().machine_ids == ("press-01", "press-02")


@pytest.mark.parametrize("value", ["", "Press 01", "press-01,invalid_machine"])
def test_rejects_invalid_machine_registry_targets(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ML_MACHINE_IDS", value)

    with pytest.raises(ValueError, match=r"ML_MACHINE_IDS|invalid machine ID"):
        MlSettings.from_env()
