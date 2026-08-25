from pathlib import Path

import pytest

from smart_factory.config import AlertSettings, MlSettings, MqttSecuritySettings, Settings
from smart_factory.domain.anomaly import AnomalySeverity


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
        "MQTT_USERNAME",
        "MQTT_PASSWORD",
        "MQTT_TLS_ENABLED",
        "MQTT_TLS_CA_CERT_PATH",
        "MQTT_TLS_CLIENT_CERT_PATH",
        "MQTT_TLS_CLIENT_KEY_PATH",
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
    assert settings.mqtt_security == MqttSecuritySettings()
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


def test_reads_mqtt_credentials_and_mutual_tls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ca_cert = tmp_path / "ca.crt"
    client_cert = tmp_path / "client.crt"
    client_key = tmp_path / "client.key"
    for path in (ca_cert, client_cert, client_key):
        path.touch()
    monkeypatch.setenv("MQTT_USERNAME", "simulator")
    monkeypatch.setenv("MQTT_PASSWORD", "secret")
    monkeypatch.setenv("MQTT_TLS_ENABLED", "true")
    monkeypatch.setenv("MQTT_TLS_CA_CERT_PATH", str(ca_cert))
    monkeypatch.setenv("MQTT_TLS_CLIENT_CERT_PATH", str(client_cert))
    monkeypatch.setenv("MQTT_TLS_CLIENT_KEY_PATH", str(client_key))

    assert MqttSecuritySettings.from_env() == MqttSecuritySettings(
        username="simulator",
        password="secret",
        tls_enabled=True,
        ca_cert_path=str(ca_cert),
        client_cert_path=str(client_cert),
        client_key_path=str(client_key),
    )


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"MQTT_PASSWORD": "secret"}, "requires MQTT_USERNAME"),
        ({"MQTT_TLS_CLIENT_CERT_PATH": "/certs/client.crt"}, "configured together"),
        ({"MQTT_TLS_CLIENT_KEY_PATH": "/certs/client.key"}, "configured together"),
        ({"MQTT_TLS_CA_CERT_PATH": "/certs/ca.crt"}, "MQTT_TLS_ENABLED=true"),
    ],
)
def test_rejects_incomplete_mqtt_security_configuration(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    message: str,
) -> None:
    for name in (
        "MQTT_USERNAME",
        "MQTT_PASSWORD",
        "MQTT_TLS_ENABLED",
        "MQTT_TLS_CA_CERT_PATH",
        "MQTT_TLS_CLIENT_CERT_PATH",
        "MQTT_TLS_CLIENT_KEY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        MqttSecuritySettings.from_env()


def test_rejects_missing_mqtt_certificate_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_TLS_ENABLED", "true")
    monkeypatch.setenv("MQTT_TLS_CA_CERT_PATH", "/missing/ca.crt")

    with pytest.raises(ValueError, match="must identify a readable file"):
        MqttSecuritySettings.from_env()


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
        "ML_EVALUATION_MINIMUM_SAMPLES",
        "ML_EVALUATION_LIMIT",
        "ML_MAX_EVALUATION_ANOMALY_RATE",
        "ML_MAX_FEATURE_PSI",
        "ML_SIGNATURE_PUBLIC_KEY_PATH",
        "ML_SIGNING_PRIVATE_KEY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = MlSettings.from_env()

    assert settings.enabled is False
    assert settings.contamination == 0.05
    assert settings.model_directory == "/models"
    assert settings.machine_ids == ("press-01",)
    assert settings.minimum_training_samples == 100
    assert settings.training_limit == 10_000
    assert settings.evaluation_minimum_samples == 30
    assert settings.evaluation_limit == 1_000
    assert settings.maximum_evaluation_anomaly_rate == 0.15
    assert settings.maximum_feature_psi == 0.25
    assert settings.signature_public_key_path is None
    assert settings.signing_private_key_path is None


def test_reads_model_signing_key_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    public_key = tmp_path / "public.pem"
    private_key = tmp_path / "private.pem"
    public_key.touch()
    private_key.touch()
    monkeypatch.setenv("ML_SIGNATURE_PUBLIC_KEY_PATH", str(public_key))
    monkeypatch.setenv("ML_SIGNING_PRIVATE_KEY_PATH", str(private_key))

    settings = MlSettings.from_env()

    assert settings.signature_public_key_path == str(public_key)
    assert settings.signing_private_key_path == str(private_key)


@pytest.mark.parametrize(
    "name",
    ["ML_SIGNATURE_PUBLIC_KEY_PATH", "ML_SIGNING_PRIVATE_KEY_PATH"],
)
def test_rejects_missing_model_signing_key_file(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.setenv(name, "/missing/key.pem")

    with pytest.raises(ValueError, match=f"{name} must identify a readable file"):
        MlSettings.from_env()


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


def test_reads_model_evaluation_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ML_EVALUATION_MINIMUM_SAMPLES", "40")
    monkeypatch.setenv("ML_EVALUATION_LIMIT", "500")
    monkeypatch.setenv("ML_MAX_EVALUATION_ANOMALY_RATE", "0.08")
    monkeypatch.setenv("ML_MAX_FEATURE_PSI", "0.2")

    settings = MlSettings.from_env()

    assert settings.evaluation_minimum_samples == 40
    assert settings.evaluation_limit == 500
    assert settings.maximum_evaluation_anomaly_rate == 0.08
    assert settings.maximum_feature_psi == 0.2


def test_rejects_evaluation_limit_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ML_EVALUATION_MINIMUM_SAMPLES", "50")
    monkeypatch.setenv("ML_EVALUATION_LIMIT", "40")

    with pytest.raises(ValueError, match="ML_EVALUATION_LIMIT must not be below"):
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


def test_alerts_default_to_disabled_high_severity(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ALERT_WEBHOOK_URL",
        "ALERT_WEBHOOK_ALLOW_INSECURE_HTTP",
        "ALERT_WEBHOOK_BEARER_TOKEN",
        "ALERT_WEBHOOK_CA_CERT_PATH",
        "ALERT_MINIMUM_SEVERITY",
        "ALERT_BATCH_SIZE",
        "ALERT_POLL_INTERVAL_SECONDS",
        "ALERT_REQUEST_TIMEOUT_SECONDS",
        "ALERT_LEASE_SECONDS",
        "ALERT_RETRY_BASE_SECONDS",
        "ALERT_RETRY_MAX_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = AlertSettings.from_env()

    assert settings.enabled is False
    assert settings.minimum_severity is AnomalySeverity.HIGH
    assert settings.routed_severities == frozenset({AnomalySeverity.HIGH})
    assert settings.batch_size == 20
    assert settings.lease_seconds == 120


def test_reads_verified_alert_webhook_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ca_cert = tmp_path / "alerts-ca.pem"
    ca_cert.touch()
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://alerts.example.test/events")
    monkeypatch.setenv("ALERT_WEBHOOK_BEARER_TOKEN", "secret")
    monkeypatch.setenv("ALERT_WEBHOOK_CA_CERT_PATH", str(ca_cert))
    monkeypatch.setenv("ALERT_MINIMUM_SEVERITY", "medium")

    settings = AlertSettings.from_env()

    assert settings.enabled is True
    assert settings.webhook_url == "https://alerts.example.test/events"
    assert settings.routed_severities == frozenset(AnomalySeverity)
    assert settings.bearer_token == "secret"
    assert settings.ca_cert_path == str(ca_cert)


def test_rejects_plain_http_alert_webhook_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://alerts.example.test/events")

    with pytest.raises(ValueError, match="approved webhook URL"):
        AlertSettings.from_env()


def test_allows_explicit_development_http_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://alerts.example.test/events")
    monkeypatch.setenv("ALERT_WEBHOOK_ALLOW_INSECURE_HTTP", "true")

    assert AlertSettings.from_env().allow_insecure_http is True


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"ALERT_WEBHOOK_BEARER_TOKEN": "secret"}, "require ALERT_WEBHOOK_URL"),
        (
            {
                "ALERT_WEBHOOK_URL": "https://alerts.example.test/events",
                "ALERT_MINIMUM_SEVERITY": "critical",
            },
            "must be medium or high",
        ),
        (
            {
                "ALERT_WEBHOOK_URL": "https://alerts.example.test/events",
                "ALERT_REQUEST_TIMEOUT_SECONDS": "30",
                "ALERT_LEASE_SECONDS": "600",
            },
            "must exceed ALERT_BATCH_SIZE",
        ),
        (
            {
                "ALERT_WEBHOOK_URL": "https://alerts.example.test/events",
                "ALERT_RETRY_BASE_SECONDS": "60",
                "ALERT_RETRY_MAX_SECONDS": "30",
            },
            "must not be below",
        ),
    ],
)
def test_rejects_invalid_alert_configuration(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    message: str,
) -> None:
    for name in (
        "ALERT_WEBHOOK_URL",
        "ALERT_WEBHOOK_BEARER_TOKEN",
        "ALERT_MINIMUM_SEVERITY",
        "ALERT_REQUEST_TIMEOUT_SECONDS",
        "ALERT_LEASE_SECONDS",
        "ALERT_RETRY_BASE_SECONDS",
        "ALERT_RETRY_MAX_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        AlertSettings.from_env()
