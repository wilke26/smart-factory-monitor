"""Environment-based runtime configuration."""

import os
import re
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from smart_factory.domain.anomaly import AnomalySeverity
from smart_factory.domain.operator_audit import OperatorAuditContext

_MACHINE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_AUDIT_CHAIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


def _required_range(name: str, default: str, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _required_float_range(name: str, default: str, minimum: float, maximum: float) -> float:
    value = float(os.getenv(name, default))
    if not isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _optional_integer(name: str) -> int | None:
    text = os.getenv(name, "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _required_boolean(name: str, default: str) -> bool:
    text = os.getenv(name, default).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _optional_text(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


@dataclass(frozen=True, slots=True)
class MqttSecuritySettings:
    """Optional broker credentials and verified TLS client material."""

    username: str | None = None
    password: str | None = field(default=None, repr=False)
    tls_enabled: bool = False
    ca_cert_path: str | None = None
    client_cert_path: str | None = None
    client_key_path: str | None = None

    @classmethod
    def from_env(cls) -> "MqttSecuritySettings":
        username = _optional_text("MQTT_USERNAME")
        password = _optional_text("MQTT_PASSWORD")
        tls_enabled = _required_boolean("MQTT_TLS_ENABLED", "false")
        ca_cert_path = _optional_text("MQTT_TLS_CA_CERT_PATH")
        client_cert_path = _optional_text("MQTT_TLS_CLIENT_CERT_PATH")
        client_key_path = _optional_text("MQTT_TLS_CLIENT_KEY_PATH")
        if password is not None and username is None:
            raise ValueError("MQTT_PASSWORD requires MQTT_USERNAME")
        if (client_cert_path is None) != (client_key_path is None):
            raise ValueError("MQTT TLS client certificate and key must be configured together")
        if not tls_enabled and any((ca_cert_path, client_cert_path, client_key_path)):
            raise ValueError("MQTT TLS certificate paths require MQTT_TLS_ENABLED=true")
        for name, path in (
            ("MQTT_TLS_CA_CERT_PATH", ca_cert_path),
            ("MQTT_TLS_CLIENT_CERT_PATH", client_cert_path),
            ("MQTT_TLS_CLIENT_KEY_PATH", client_key_path),
        ):
            if path is not None and (not Path(path).is_file() or not os.access(path, os.R_OK)):
                raise ValueError(f"{name} must identify a readable file")
        return cls(
            username=username,
            password=password,
            tls_enabled=tls_enabled,
            ca_cert_path=ca_cert_path,
            client_cert_path=client_cert_path,
            client_key_path=client_key_path,
        )


@dataclass(frozen=True, slots=True)
class MlSettings:
    """Configuration shared by offline training and optional online inference."""

    enabled: bool
    model_directory: str
    machine_ids: tuple[str, ...]
    contamination: float
    minimum_training_samples: int
    training_limit: int
    signature_public_key_path: str | None = None
    signing_private_key_path: str | None = field(default=None, repr=False)
    evaluation_minimum_samples: int = 30
    evaluation_limit: int = 1_000
    maximum_evaluation_anomaly_rate: float = 0.15
    maximum_feature_psi: float = 0.25

    @classmethod
    def from_env(cls) -> "MlSettings":
        minimum_samples = _required_range("ML_MINIMUM_TRAINING_SAMPLES", "100", 20, 100_000)
        training_limit = _required_range("ML_TRAINING_LIMIT", "10000", 20, 1_000_000)
        if training_limit < minimum_samples:
            raise ValueError("ML_TRAINING_LIMIT must not be below ML_MINIMUM_TRAINING_SAMPLES")
        evaluation_minimum_samples = _required_range(
            "ML_EVALUATION_MINIMUM_SAMPLES", "30", 20, 100_000
        )
        evaluation_limit = _required_range("ML_EVALUATION_LIMIT", "1000", 20, 1_000_000)
        if evaluation_limit < evaluation_minimum_samples:
            raise ValueError("ML_EVALUATION_LIMIT must not be below ML_EVALUATION_MINIMUM_SAMPLES")
        model_directory = os.getenv("ML_MODEL_DIRECTORY", "/models").strip()
        if not model_directory:
            raise ValueError("ML_MODEL_DIRECTORY must not be empty")
        configured_machine_ids = os.getenv(
            "ML_MACHINE_IDS",
            os.getenv("ML_MACHINE_ID", os.getenv("MACHINE_ID", "press-01")),
        )
        machine_ids = tuple(
            dict.fromkeys(
                part.strip() for part in configured_machine_ids.split(",") if part.strip()
            )
        )
        if not machine_ids:
            raise ValueError("ML_MACHINE_IDS must contain at least one machine ID")
        invalid_machine_ids = [
            machine_id
            for machine_id in machine_ids
            if not _MACHINE_ID_PATTERN.fullmatch(machine_id)
        ]
        if invalid_machine_ids:
            raise ValueError(f"invalid machine ID in ML_MACHINE_IDS: {invalid_machine_ids[0]}")
        signature_public_key_path = _optional_text("ML_SIGNATURE_PUBLIC_KEY_PATH")
        signing_private_key_path = _optional_text("ML_SIGNING_PRIVATE_KEY_PATH")
        for name, path in (
            ("ML_SIGNATURE_PUBLIC_KEY_PATH", signature_public_key_path),
            ("ML_SIGNING_PRIVATE_KEY_PATH", signing_private_key_path),
        ):
            if path is not None and (not Path(path).is_file() or not os.access(path, os.R_OK)):
                raise ValueError(f"{name} must identify a readable file")
        return cls(
            enabled=_required_boolean("ML_ANOMALY_DETECTION_ENABLED", "false"),
            model_directory=model_directory,
            machine_ids=machine_ids,
            contamination=_required_float_range("ML_CONTAMINATION", "0.05", 0.001, 0.5),
            minimum_training_samples=minimum_samples,
            training_limit=training_limit,
            signature_public_key_path=signature_public_key_path,
            signing_private_key_path=signing_private_key_path,
            evaluation_minimum_samples=evaluation_minimum_samples,
            evaluation_limit=evaluation_limit,
            maximum_evaluation_anomaly_rate=_required_float_range(
                "ML_MAX_EVALUATION_ANOMALY_RATE", "0.15", 0.0, 1.0
            ),
            maximum_feature_psi=_required_float_range("ML_MAX_FEATURE_PSI", "0.25", 0.0, 10.0),
        )


@dataclass(frozen=True, slots=True)
class AlertSettings:
    """Configuration for durable webhook alert delivery."""

    webhook_url: str | None
    minimum_severity: AnomalySeverity
    batch_size: int
    poll_interval_seconds: float
    request_timeout_seconds: float
    lease_seconds: int
    retry_base_seconds: float
    retry_max_seconds: float
    bearer_token: str | None = field(default=None, repr=False)
    ca_cert_path: str | None = None
    allow_insecure_http: bool = False

    @property
    def enabled(self) -> bool:
        return self.webhook_url is not None

    @property
    def routed_severities(self) -> frozenset[AnomalySeverity]:
        if self.minimum_severity is AnomalySeverity.HIGH:
            return frozenset({AnomalySeverity.HIGH})
        return frozenset(AnomalySeverity)

    @classmethod
    def from_env(cls) -> "AlertSettings":
        webhook_url = _optional_text("ALERT_WEBHOOK_URL")
        bearer_token = _optional_text("ALERT_WEBHOOK_BEARER_TOKEN")
        ca_cert_path = _optional_text("ALERT_WEBHOOK_CA_CERT_PATH")
        allow_insecure_http = _required_boolean("ALERT_WEBHOOK_ALLOW_INSECURE_HTTP", "false")
        if webhook_url is None and any((bearer_token, ca_cert_path)):
            raise ValueError("alert webhook credentials require ALERT_WEBHOOK_URL")
        if webhook_url is not None:
            parsed = urlsplit(webhook_url)
            allowed_schemes = {"https", "http"} if allow_insecure_http else {"https"}
            if (
                parsed.scheme not in allowed_schemes
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError("ALERT_WEBHOOK_URL must be an absolute approved webhook URL")
        if ca_cert_path is not None and (
            not Path(ca_cert_path).is_file() or not os.access(ca_cert_path, os.R_OK)
        ):
            raise ValueError("ALERT_WEBHOOK_CA_CERT_PATH must identify a readable file")
        severity_text = os.getenv("ALERT_MINIMUM_SEVERITY", "high").strip().lower()
        try:
            minimum_severity = AnomalySeverity(severity_text)
        except ValueError as error:
            raise ValueError("ALERT_MINIMUM_SEVERITY must be medium or high") from error
        batch_size = _required_range("ALERT_BATCH_SIZE", "20", 1, 1_000)
        request_timeout = _required_float_range("ALERT_REQUEST_TIMEOUT_SECONDS", "5.0", 0.1, 60.0)
        lease_seconds = _required_range("ALERT_LEASE_SECONDS", "120", 1, 86_400)
        if lease_seconds <= request_timeout * batch_size:
            raise ValueError(
                "ALERT_LEASE_SECONDS must exceed ALERT_BATCH_SIZE times "
                "ALERT_REQUEST_TIMEOUT_SECONDS"
            )
        retry_base = _required_float_range("ALERT_RETRY_BASE_SECONDS", "5.0", 0.1, 3_600.0)
        retry_max = _required_float_range("ALERT_RETRY_MAX_SECONDS", "300.0", 0.1, 86_400.0)
        if retry_max < retry_base:
            raise ValueError("ALERT_RETRY_MAX_SECONDS must not be below ALERT_RETRY_BASE_SECONDS")
        return cls(
            webhook_url=webhook_url,
            minimum_severity=minimum_severity,
            batch_size=batch_size,
            poll_interval_seconds=_required_float_range(
                "ALERT_POLL_INTERVAL_SECONDS", "2.0", 0.1, 300.0
            ),
            request_timeout_seconds=request_timeout,
            lease_seconds=lease_seconds,
            retry_base_seconds=retry_base,
            retry_max_seconds=retry_max,
            bearer_token=bearer_token,
            ca_cert_path=ca_cert_path,
            allow_insecure_http=allow_insecure_http,
        )


@dataclass(frozen=True, slots=True)
class OperatorAuditSettings:
    """Explicit operator identity and justification for privileged commands."""

    actor: str
    reason: str
    correlation_id: UUID

    @property
    def context(self) -> OperatorAuditContext:
        return OperatorAuditContext(
            actor=self.actor,
            reason=self.reason,
            correlation_id=self.correlation_id,
        )

    @classmethod
    def from_env(cls) -> "OperatorAuditSettings":
        actor = os.getenv("AUDIT_ACTOR", "").strip()
        reason = os.getenv("AUDIT_REASON", "").strip()
        raw_correlation_id = os.getenv("AUDIT_CORRELATION_ID", "").strip()
        if not actor:
            raise ValueError("AUDIT_ACTOR is required for privileged operations")
        if not reason:
            raise ValueError("AUDIT_REASON is required for privileged operations")
        if not raw_correlation_id:
            raise ValueError("AUDIT_CORRELATION_ID is required for privileged operations")
        try:
            correlation_id = UUID(raw_correlation_id)
        except ValueError as error:
            raise ValueError("AUDIT_CORRELATION_ID must be a UUID") from error
        return cls(actor=actor, reason=reason, correlation_id=correlation_id)


@dataclass(frozen=True, slots=True)
class AuditCheckpointSettings:
    """Key material and destination for portable audit-chain checkpoints."""

    chain_id: str
    checkpoint_path: str
    public_key_path: str
    private_key_path: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, *, require_private_key: bool) -> "AuditCheckpointSettings":
        chain_id = os.getenv("AUDIT_CHAIN_ID", "").strip()
        checkpoint_path = os.getenv("AUDIT_CHECKPOINT_PATH", "").strip()
        public_key_path = os.getenv("AUDIT_ATTESTATION_PUBLIC_KEY_PATH", "").strip()
        private_key_path = _optional_text("AUDIT_ATTESTATION_PRIVATE_KEY_PATH")
        if not chain_id:
            raise ValueError("AUDIT_CHAIN_ID is required for audit checkpoints")
        if not _AUDIT_CHAIN_ID_PATTERN.fullmatch(chain_id):
            raise ValueError("AUDIT_CHAIN_ID contains unsupported characters")
        if not checkpoint_path:
            raise ValueError("AUDIT_CHECKPOINT_PATH is required for audit checkpoints")
        if not public_key_path:
            raise ValueError("AUDIT_ATTESTATION_PUBLIC_KEY_PATH is required")
        if require_private_key and private_key_path is None:
            raise ValueError("AUDIT_ATTESTATION_PRIVATE_KEY_PATH is required for export")
        for name, path in (
            ("AUDIT_ATTESTATION_PUBLIC_KEY_PATH", public_key_path),
            ("AUDIT_ATTESTATION_PRIVATE_KEY_PATH", private_key_path),
        ):
            if path is not None and (not Path(path).is_file() or not os.access(path, os.R_OK)):
                raise ValueError(f"{name} must identify a readable file")
        return cls(
            chain_id=chain_id,
            checkpoint_path=checkpoint_path,
            public_key_path=public_key_path,
            private_key_path=private_key_path,
        )


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
    maximum_temperature_c: float
    maximum_vibration_mm_s: float
    maximum_power_kw: float
    minimum_production_rate: int
    mqtt_session_expiry_seconds: int = 86_400
    mqtt_receive_maximum: int = 20
    monitoring_host: str = "0.0.0.0"
    monitoring_port: int = 8000
    mqtt_security: MqttSecuritySettings = field(default_factory=MqttSecuritySettings)

    @property
    def topic(self) -> str:
        return f"factory/{self.factory_area}/{self.machine_id}/telemetry"

    @classmethod
    def from_env(cls) -> "Settings":
        interval = float(os.getenv("PUBLISH_INTERVAL_SECONDS", "2.0"))
        if interval <= 0:
            raise ValueError("PUBLISH_INTERVAL_SECONDS must be greater than zero")
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
        maximum_temperature = _required_float_range(
            "ANOMALY_MAX_TEMPERATURE_C", "90.0", -50.0, 250.0
        )
        maximum_vibration = _required_float_range("ANOMALY_MAX_VIBRATION_MM_S", "7.0", 0.0, 100.0)
        maximum_power = _required_float_range("ANOMALY_MAX_POWER_KW", "30.0", 0.0, 500.0)
        minimum_production = _required_range("ANOMALY_MIN_PRODUCTION_RATE", "25", 0, 10_000)
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
            simulator_seed=_optional_integer("SIMULATOR_SEED"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://smart_factory:smart_factory_dev@localhost:5432/smart_factory",
            ),
            database_pool_min_size=pool_min_size,
            database_pool_max_size=pool_max_size,
            database_connect_timeout_seconds=database_timeout,
            maximum_temperature_c=maximum_temperature,
            maximum_vibration_mm_s=maximum_vibration,
            maximum_power_kw=maximum_power,
            minimum_production_rate=minimum_production,
            mqtt_session_expiry_seconds=_required_range(
                "MQTT_SESSION_EXPIRY_SECONDS", "86400", 1, 2_147_483_647
            ),
            mqtt_receive_maximum=_required_range("MQTT_RECEIVE_MAXIMUM", "20", 1, 65_535),
            monitoring_host=os.getenv("MONITORING_HOST", "0.0.0.0"),
            monitoring_port=_required_range("MONITORING_PORT", "8000", 1, 65_535),
            mqtt_security=MqttSecuritySettings.from_env(),
        )
