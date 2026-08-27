from unittest.mock import Mock, patch

import pytest

from smart_factory.verify_audit_main import AuditChainVerificationError, run


def runtime_settings() -> Mock:
    return Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )


@patch("smart_factory.verify_audit_main.PsycopgOperatorAuditTrail")
def test_verifies_and_closes_audit_store(trail_type: Mock) -> None:
    trail_type.return_value.verify.return_value = Mock(
        valid=True,
        event_count=2,
        head_hash="a" * 64,
    )

    run(runtime_settings())

    trail_type.return_value.open.assert_called_once_with(timeout=10)
    trail_type.return_value.verify.assert_called_once_with()
    trail_type.return_value.close.assert_called_once_with()


@patch("smart_factory.verify_audit_main.PsycopgOperatorAuditTrail")
def test_fails_when_chain_is_invalid_and_still_closes(trail_type: Mock) -> None:
    trail_type.return_value.verify.return_value = Mock(
        valid=False,
        invalid_sequence_number=3,
    )

    with pytest.raises(AuditChainVerificationError, match="sequence 3"):
        run(runtime_settings())

    trail_type.return_value.close.assert_called_once_with()
