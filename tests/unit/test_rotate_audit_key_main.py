from unittest.mock import Mock, patch
from uuid import UUID

from smart_factory.config import AuditCheckpointSettings, OperatorAuditSettings
from smart_factory.rotate_audit_key_main import run


def runtime_settings() -> Mock:
    return Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )


@patch("smart_factory.rotate_audit_key_main.AuditAttestationKeyRotationService")
@patch("smart_factory.rotate_audit_key_main.FilesystemAuditAttestationKeyRotator")
@patch("smart_factory.rotate_audit_key_main.AuditAttestationKeyring")
@patch("smart_factory.rotate_audit_key_main.PsycopgOperatorAuditTrail")
def test_rotates_and_closes_audit_trail(
    trail_type: Mock,
    keyring_type: Mock,
    rotator_type: Mock,
    service_type: Mock,
) -> None:
    service_type.return_value.rotate.return_value = Mock(
        transition_id=UUID("22222222-2222-2222-2222-222222222222"),
        previous_key_id="a" * 64,
        new_key_id="b" * 64,
    )
    checkpoint_settings = AuditCheckpointSettings(
        chain_id="factory-production",
        checkpoint_path="/checkpoints/checkpoint.json",
        private_key_path="/keys/private.pem",
        public_key_path="/keys/public.pem",
        keyring_path="/keys/keyring",
        trusted_root_key_id_path="/keys/trusted-root-key-id",
    )
    audit_settings = OperatorAuditSettings(
        actor="security-operator",
        reason="ticket-456",
        correlation_id=UUID("11111111-1111-1111-1111-111111111111"),
    )

    run(runtime_settings(), checkpoint_settings, audit_settings)

    trail_type.return_value.open.assert_called_once_with(timeout=10)
    trail_type.return_value.close.assert_called_once_with()
    keyring_type.assert_called_once()
    rotator_type.assert_called_once()
    service_type.return_value.rotate.assert_called_once_with(audit_settings.context)
