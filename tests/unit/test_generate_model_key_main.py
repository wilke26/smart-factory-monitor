from pathlib import Path
from unittest.mock import Mock, patch

from smart_factory.generate_model_key_main import main


@patch("smart_factory.generate_model_key_main.LOGGER")
@patch("smart_factory.generate_model_key_main.ensure_ed25519_key_pair", return_value=True)
@patch("smart_factory.generate_model_key_main.configure_logging")
def test_generates_configured_key_pair_without_logging_private_path(
    configure_logging: Mock,
    ensure_key_pair: Mock,
    logger: Mock,
) -> None:
    with patch.dict(
        "os.environ",
        {
            "LOG_LEVEL": "warning",
            "ML_SIGNING_PRIVATE_KEY_PATH": "/private/key.pem",
            "ML_SIGNATURE_PUBLIC_KEY_PATH": "/public/key.pem",
        },
        clear=True,
    ):
        main()

    configure_logging.assert_called_once_with("WARNING")
    ensure_key_pair.assert_called_once_with(
        Path("/private/key.pem"),
        Path("/public/key.pem"),
    )
    assert logger.info.call_args.args[0] == "ml_signing_key_ready"
    assert logger.info.call_args.kwargs["extra"] == {
        "key_created": True,
        "public_key_path": "/public/key.pem",
    }
