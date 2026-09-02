from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from smart_factory.generate_audit_key_main import main
from smart_factory.infrastructure.audit.checkpoint import AuditCheckpointError


@patch("smart_factory.generate_audit_key_main.LOGGER")
@patch("smart_factory.generate_audit_key_main.AuditAttestationKeyring")
@patch("smart_factory.generate_audit_key_main.public_key_id", return_value="a" * 64)
@patch("smart_factory.generate_audit_key_main.ensure_ed25519_key_pair", return_value=True)
@patch("smart_factory.generate_audit_key_main.configure_logging")
def test_generates_separate_audit_attestation_key_pair(
    configure_logging: Mock,
    ensure_key_pair: Mock,
    public_key_id_mock: Mock,
    keyring_type: Mock,
    logger: Mock,
) -> None:
    keyring_type.return_value.initialize.return_value = "a" * 64
    with patch.dict(
        "os.environ",
        {
            "LOG_LEVEL": "warning",
            "AUDIT_ATTESTATION_PRIVATE_KEY_PATH": "/private/audit.pem",
            "AUDIT_ATTESTATION_PUBLIC_KEY_PATH": "/public/audit.pem",
        },
        clear=True,
    ):
        main()

    configure_logging.assert_called_once_with("WARNING")
    ensure_key_pair.assert_called_once_with(
        Path("/private/audit.pem"),
        Path("/public/audit.pem"),
    )
    public_key_id_mock.assert_called_once_with(Path("/public/audit.pem"))
    assert logger.info.call_args.args[0] == "audit_attestation_key_ready"
    assert "private" not in str(logger.info.call_args)
    assert logger.info.call_args.kwargs["extra"]["key_id"] == "a" * 64


@patch("smart_factory.generate_audit_key_main.LOGGER")
def test_development_mode_creates_colocated_root_marker(logger: Mock, tmp_path: Path) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    keyring_path = tmp_path / "keyring"
    root_path = tmp_path / "trusted-root-key-id"
    with patch.dict(
        "os.environ",
        {
            "AUDIT_ATTESTATION_PRIVATE_KEY_PATH": str(private_path),
            "AUDIT_ATTESTATION_PUBLIC_KEY_PATH": str(public_path),
            "AUDIT_ATTESTATION_KEYRING_PATH": str(keyring_path),
            "AUDIT_ATTESTATION_ROOT_KEY_ID_PATH": str(root_path),
            "AUDIT_ATTESTATION_ALLOW_COLOCATED_ROOT": "true",
        },
        clear=True,
    ):
        main()

    assert root_path.read_text().strip() == logger.info.call_args.kwargs["extra"]["key_id"]
    assert logger.info.call_args.kwargs["extra"]["external_root_pin_required"] is False


def test_existing_key_requires_external_pin_without_development_mode(tmp_path: Path) -> None:
    environment = {
        "AUDIT_ATTESTATION_PRIVATE_KEY_PATH": str(tmp_path / "private.pem"),
        "AUDIT_ATTESTATION_PUBLIC_KEY_PATH": str(tmp_path / "public.pem"),
        "AUDIT_ATTESTATION_KEYRING_PATH": str(tmp_path / "keyring"),
    }
    with patch.dict("os.environ", environment, clear=True):
        main()
        with pytest.raises(ValueError, match="TRUSTED_ROOT_KEY_ID is required"):
            main()


def test_external_pin_must_match_initial_public_key(tmp_path: Path) -> None:
    with (
        patch.dict(
            "os.environ",
            {
                "AUDIT_ATTESTATION_PRIVATE_KEY_PATH": str(tmp_path / "private.pem"),
                "AUDIT_ATTESTATION_PUBLIC_KEY_PATH": str(tmp_path / "public.pem"),
                "AUDIT_ATTESTATION_KEYRING_PATH": str(tmp_path / "keyring"),
                "AUDIT_ATTESTATION_TRUSTED_ROOT_KEY_ID": "a" * 64,
            },
            clear=True,
        ),
        pytest.raises(AuditCheckpointError, match="does not match trusted root"),
    ):
        main()
