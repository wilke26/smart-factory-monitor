import pytest

from smart_factory.config import Settings


def test_defaults_publish_to_v01_acceptance_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MQTT_HOST",
        "MQTT_PORT",
        "MQTT_QOS",
        "MQTT_KEEPALIVE",
        "MQTT_CLIENT_ID",
        "FACTORY_AREA",
        "MACHINE_ID",
        "PUBLISH_INTERVAL_SECONDS",
        "SIMULATOR_SEED",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.topic == "factory/hall-a/press-01/telemetry"
    assert settings.mqtt_host == "localhost"
    assert settings.mqtt_qos == 1


def test_reads_optional_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMULATOR_SEED", "42")

    assert Settings.from_env().simulator_seed == 42


@pytest.mark.parametrize(("name", "value"), [("MQTT_QOS", "3"), ("MQTT_PORT", "0")])
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
