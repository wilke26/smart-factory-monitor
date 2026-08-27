"""Signed, portable checkpoints for the privileged-operation audit chain."""

from __future__ import annotations

import json
import os
from base64 import b64decode, b64encode
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from smart_factory.domain.audit_checkpoint import AuditCheckpoint, SignedAuditCheckpoint
from smart_factory.domain.operator_audit import AuditChainVerification
from smart_factory.infrastructure.ml.artifact_signing import (
    ArtifactSigner,
    ArtifactSigningError,
    ArtifactVerifier,
)

MAX_CHECKPOINT_BYTES = 65_536


class AuditCheckpointError(ValueError):
    """A checkpoint, signature, key identity, or destination is invalid."""


def canonical_checkpoint_payload(checkpoint: AuditCheckpoint) -> bytes:
    document = {
        "chain_id": checkpoint.chain_id,
        "checkpoint_id": str(checkpoint.checkpoint_id),
        "created_at": checkpoint.created_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "event_count": checkpoint.event_count,
        "head_hash": checkpoint.head_hash,
        "key_id": checkpoint.key_id,
        "schema_version": checkpoint.schema_version,
    }
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def public_key_id(public_key_path: Path) -> str:
    try:
        loaded = serialization.load_pem_public_key(public_key_path.read_bytes())
    except (OSError, ValueError) as error:
        raise AuditCheckpointError("could not load audit attestation public key") from error
    if not isinstance(loaded, Ed25519PublicKey):
        raise AuditCheckpointError("audit attestation public key is not an Ed25519 key")
    canonical_key = loaded.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return sha256(canonical_key).hexdigest()


def create_signed_checkpoint(
    verification: AuditChainVerification,
    *,
    chain_id: str,
    signer: ArtifactSigner,
    public_key_path: Path,
    created_at: datetime | None = None,
) -> SignedAuditCheckpoint:
    if not verification.valid:
        raise AuditCheckpointError("cannot checkpoint an invalid operator audit chain")
    checkpoint = AuditCheckpoint(
        chain_id=chain_id,
        created_at=created_at or datetime.now(UTC),
        event_count=verification.event_count,
        head_hash=verification.head_hash,
        key_id=public_key_id(public_key_path),
    )
    payload = canonical_checkpoint_payload(checkpoint)
    signature = signer.sign(payload)
    try:
        ArtifactVerifier.from_public_key_file(public_key_path).verify(payload, signature)
    except ArtifactSigningError as error:
        raise AuditCheckpointError("audit attestation key pair does not match") from error
    return SignedAuditCheckpoint(
        checkpoint=checkpoint,
        signature=b64encode(signature).decode("ascii"),
    )


def verify_signed_checkpoint(
    envelope: SignedAuditCheckpoint,
    *,
    verifier: ArtifactVerifier,
    public_key_path: Path,
    expected_chain_id: str,
) -> AuditCheckpoint:
    checkpoint = envelope.checkpoint
    if checkpoint.chain_id != expected_chain_id:
        raise AuditCheckpointError("audit checkpoint belongs to an unexpected chain")
    if checkpoint.key_id != public_key_id(public_key_path):
        raise AuditCheckpointError("audit checkpoint key identity does not match verifier")
    try:
        verifier.verify(
            canonical_checkpoint_payload(checkpoint),
            b64decode(envelope.signature, validate=True),
        )
    except ArtifactSigningError as error:
        raise AuditCheckpointError("audit checkpoint signature is invalid") from error
    return checkpoint


def write_signed_checkpoint(path: Path, envelope: SignedAuditCheckpoint) -> None:
    """Publish one complete checkpoint without replacing existing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (envelope.model_dump_json(indent=2) + "\n").encode()
    if len(payload) > MAX_CHECKPOINT_BYTES:
        raise AuditCheckpointError("signed audit checkpoint exceeds size limit")
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as file:
        temporary_path = Path(file.name)
        file.write(payload)
        file.flush()
        os.fsync(file.fileno())
    try:
        os.chmod(temporary_path, 0o644)
        try:
            os.link(temporary_path, path)
        except FileExistsError as error:
            raise AuditCheckpointError("audit checkpoint destination already exists") from error
    finally:
        temporary_path.unlink(missing_ok=True)


def load_signed_checkpoint(path: Path) -> SignedAuditCheckpoint:
    try:
        if path.stat().st_size > MAX_CHECKPOINT_BYTES:
            raise AuditCheckpointError("signed audit checkpoint exceeds size limit")
        return SignedAuditCheckpoint.model_validate_json(path.read_bytes())
    except AuditCheckpointError:
        raise
    except (OSError, ValidationError) as error:
        raise AuditCheckpointError("could not load a valid signed audit checkpoint") from error
