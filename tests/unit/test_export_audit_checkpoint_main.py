from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from smart_factory.config import AuditCheckpointSettings
from smart_factory.domain.operator_audit import AuditChainVerification
from smart_factory.export_audit_checkpoint_main import run
from smart_factory.infrastructure.audit.checkpoint import (
    AuditCheckpointError,
    load_signed_checkpoint,
)


def runtime_settings() -> Mock:
    return Mock(
        database_url="postgresql://database/smart_factory",
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=10,
    )


@patch("smart_factory.export_audit_checkpoint_main.PsycopgOperatorAuditTrail")
def test_exports_verified_chain_and_closes_store(
    trail_type: Mock,
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = model_signing_keys
    output_path = tmp_path / "checkpoint.json"
    trail_type.return_value.verify.return_value = AuditChainVerification(
        valid=True,
        event_count=2,
        head_hash="a" * 64,
    )
    settings = AuditCheckpointSettings(
        chain_id="factory-production",
        checkpoint_path=str(output_path),
        private_key_path=str(private_path),
        public_key_path=str(public_path),
    )

    run(runtime_settings(), settings)

    assert load_signed_checkpoint(output_path).checkpoint.event_count == 2
    trail_type.return_value.open.assert_called_once_with(timeout=10)
    trail_type.return_value.close.assert_called_once_with()


@patch("smart_factory.export_audit_checkpoint_main.PsycopgOperatorAuditTrail")
def test_invalid_chain_is_not_exported_and_store_is_closed(
    trail_type: Mock,
    tmp_path: Path,
    model_signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = model_signing_keys
    output_path = tmp_path / "checkpoint.json"
    trail_type.return_value.verify.return_value = AuditChainVerification(
        valid=False,
        event_count=2,
        head_hash="a" * 64,
        invalid_sequence_number=2,
    )
    settings = AuditCheckpointSettings(
        chain_id="factory-production",
        checkpoint_path=str(output_path),
        private_key_path=str(private_path),
        public_key_path=str(public_path),
    )

    with pytest.raises(AuditCheckpointError, match="sequence 2"):
        run(runtime_settings(), settings)

    assert not output_path.exists()
    trail_type.return_value.close.assert_called_once_with()
