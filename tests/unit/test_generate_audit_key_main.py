from pathlib import Path
from unittest.mock import Mock, patch

from smart_factory.generate_audit_key_main import main


@patch("smart_factory.generate_audit_key_main.LOGGER")
@patch("smart_factory.generate_audit_key_main.ensure_ed25519_key_pair", return_value=True)
@patch("smart_factory.generate_audit_key_main.configure_logging")
def test_generates_separate_audit_attestation_key_pair(
    configure_logging: Mock,
    ensure_key_pair: Mock,
    logger: Mock,
) -> None:
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
    assert logger.info.call_args.args[0] == "audit_attestation_key_ready"
    assert "private" not in str(logger.info.call_args)
