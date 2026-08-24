import ssl
from unittest.mock import Mock

from smart_factory.infrastructure.mqtt.security import configure_mqtt_security


def test_configures_username_and_password() -> None:
    client = Mock()

    configure_mqtt_security(
        client,
        username="consumer",
        password="secret",
        tls_enabled=False,
        ca_cert_path=None,
        client_cert_path=None,
        client_key_path=None,
    )

    client.username_pw_set.assert_called_once_with("consumer", "secret")
    client.tls_set.assert_not_called()


def test_configures_verified_mutual_tls() -> None:
    client = Mock()

    configure_mqtt_security(
        client,
        username=None,
        password=None,
        tls_enabled=True,
        ca_cert_path="/certs/ca.crt",
        client_cert_path="/certs/client.crt",
        client_key_path="/certs/client.key",
    )

    client.tls_set.assert_called_once_with(
        ca_certs="/certs/ca.crt",
        certfile="/certs/client.crt",
        keyfile="/certs/client.key",
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set.assert_not_called()
