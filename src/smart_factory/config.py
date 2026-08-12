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
    mqtt_consumer_client_id: str
    mqtt_topic_filter: str
    factory_area: str
    machine_id: str
    publish_interval_seconds: float
    simulator_seed: int | None
    log_level: str
    database_url: str
    database_pool_min_size: int
    database_pool_max_size: int
    database_connect_timeout_seconds: float

    @property
    def topic(self) -> str:
        return f"factory/{self.factory_area}/{self.machine_id}/telemetry"

    @classmethod
    def from_env(cls) -> "Settings":
        interval = float(os.getenv("PUBLISH_INTERVAL_SECONDS", "2.0"))
        if interval <= 0:
            raise ValueError("PUBLISH_INTERVAL_SECONDS must be greater than zero")
        seed_text = os.getenv("SIMULATOR_SEED", "").strip()
        topic_filter = os.getenv("MQTT_TOPIC_FILTER", "factory/+/+/telemetry").strip()
        if not topic_filter:
            raise ValueError("MQTT_TOPIC_FILTER must not be empty")
        pool_min_size = _required_range("DATABASE_POOL_MIN_SIZE", "1", 1, 100)
        pool_max_size = _required_range("DATABASE_POOL_MAX_SIZE", "4", 1, 100)
        if pool_min_size > pool_max_size:
            raise ValueError("DATABASE_POOL_MIN_SIZE must not exceed DATABASE_POOL_MAX_SIZE")
        database_timeout = float(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "10.0"))
        if database_timeout <= 0:
            raise ValueError("DATABASE_CONNECT_TIMEOUT_SECONDS must be greater than zero")
        return cls(
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=_required_range("MQTT_PORT", "1883", 1, 65535),
            mqtt_keepalive=_required_range("MQTT_KEEPALIVE", "60", 1, 65535),
            mqtt_qos=_required_range("MQTT_QOS", "1", 0, 2),
            mqtt_client_id=os.getenv("MQTT_CLIENT_ID", "smart-factory-simulator"),
            mqtt_consumer_client_id=os.getenv("MQTT_CONSUMER_CLIENT_ID", "smart-factory-consumer"),
            mqtt_topic_filter=topic_filter,
            factory_area=os.getenv("FACTORY_AREA", "hall-a"),
            machine_id=os.getenv("MACHINE_ID", "press-01"),
            publish_interval_seconds=interval,
            simulator_seed=int(seed_text) if seed_text else None,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://smart_factory:smart_factory_dev@localhost:5432/smart_factory",
            ),
            database_pool_min_size=pool_min_size,
            database_pool_max_size=pool_max_size,
            database_connect_timeout_seconds=database_timeout,
        )
