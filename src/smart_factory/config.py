"""Environment-based runtime configuration."""

import os
from dataclasses import dataclass


def _required_range(name: str, default: str, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_keepalive: int
    mqtt_qos: int
    mqtt_client_id: str
    factory_area: str
    machine_id: str
    publish_interval_seconds: float
    simulator_seed: int | None
    log_level: str

    @property
    def topic(self) -> str:
        return f"factory/{self.factory_area}/{self.machine_id}/telemetry"

    @classmethod
    def from_env(cls) -> "Settings":
        interval = float(os.getenv("PUBLISH_INTERVAL_SECONDS", "2.0"))
        if interval <= 0:
            raise ValueError("PUBLISH_INTERVAL_SECONDS must be greater than zero")
        seed_text = os.getenv("SIMULATOR_SEED", "").strip()
        return cls(
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=_required_range("MQTT_PORT", "1883", 1, 65535),
            mqtt_keepalive=_required_range("MQTT_KEEPALIVE", "60", 1, 65535),
            mqtt_qos=_required_range("MQTT_QOS", "1", 0, 2),
            mqtt_client_id=os.getenv("MQTT_CLIENT_ID", "smart-factory-simulator"),
            factory_area=os.getenv("FACTORY_AREA", "hall-a"),
            machine_id=os.getenv("MACHINE_ID", "press-01"),
            publish_interval_seconds=interval,
            simulator_seed=int(seed_text) if seed_text else None,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
