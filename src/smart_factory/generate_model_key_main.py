"""Console entry point for local model-signing key initialization."""

import logging
import os
from pathlib import Path

from smart_factory.infrastructure.ml.artifact_signing import ensure_ed25519_key_pair
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def main() -> None:
    configure_logging(os.getenv("LOG_LEVEL", "INFO").upper())
    private_path = Path(
        os.getenv("ML_SIGNING_PRIVATE_KEY_PATH", "/run/ml-signing/private/private.pem")
    )
    public_path = Path(
        os.getenv("ML_SIGNATURE_PUBLIC_KEY_PATH", "/run/ml-signing/public/public.pem")
    )
    created = ensure_ed25519_key_pair(private_path, public_path)
    LOGGER.info(
        "ml_signing_key_ready",
        extra={"key_created": created, "public_key_path": str(public_path)},
    )


if __name__ == "__main__":
    main()
