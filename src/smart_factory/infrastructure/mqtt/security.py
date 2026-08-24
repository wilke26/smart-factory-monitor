"""Shared secure-client configuration for MQTT adapters."""

from __future__ import annotations

import ssl

import paho.mqtt.client as mqtt


def configure_mqtt_security(
    client: mqtt.Client,
    *,
    username: str | None,
    password: str | None,
    tls_enabled: bool,
    ca_cert_path: str | None,
    client_cert_path: str | None,
    client_key_path: str | None,
) -> None:
    """Configure credentials and verified TLS before the first connection."""
    if username is not None:
        client.username_pw_set(username, password)
    if tls_enabled:
        client.tls_set(
            ca_certs=ca_cert_path,
            certfile=client_cert_path,
            keyfile=client_key_path,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
