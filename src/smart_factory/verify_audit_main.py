"""Console entry point for independent operator audit-chain verification."""

import logging

from smart_factory.config import Settings
from smart_factory.infrastructure.database.operator_audit import PsycopgOperatorAuditTrail
from smart_factory.logging import configure_logging

LOGGER = logging.getLogger(__name__)


class AuditChainVerificationError(RuntimeError):
    """Persisted privileged-operation evidence is incomplete or inconsistent."""


def run(settings: Settings) -> None:
    audit_trail = PsycopgOperatorAuditTrail(
        settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
    )
    try:
        audit_trail.open(timeout=settings.database_connect_timeout_seconds)
        result = audit_trail.verify()
    finally:
        audit_trail.close()
    if not result.valid:
        raise AuditChainVerificationError(
            f"operator audit chain invalid at sequence {result.invalid_sequence_number}"
        )
    LOGGER.info(
        "operator_audit_chain_verified",
        extra={"event_count": result.event_count, "head_hash": result.head_hash},
    )


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    run(settings)


if __name__ == "__main__":
    main()
