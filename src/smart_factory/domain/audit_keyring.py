"""Immutable contracts for audit-attestation key rotation."""

from base64 import b64decode
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditKeyTransition(BaseModel):
    """One explicitly authorized transition between attestation keys."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    transition_id: UUID = Field(default_factory=uuid4)
    chain_id: Annotated[
        str,
        Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"),
    ]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previous_key_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    new_key_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit key transition timestamp must include a UTC offset")
        return value


class SignedAuditKeyTransition(BaseModel):
    """Transition authorized by both the previous and replacement private keys."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    transition: AuditKeyTransition
    previous_signature: Annotated[str, Field(min_length=1, max_length=128)]
    new_signature: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("previous_signature", "new_signature")
    @classmethod
    def signature_must_be_ed25519_base64(cls, value: str) -> str:
        try:
            decoded = b64decode(value, validate=True)
        except ValueError as error:
            raise ValueError("audit key transition signature must be base64") from error
        if len(decoded) != 64:
            raise ValueError("audit key transition signature must be Ed25519")
        return value


class AuditKeyRotationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    transition_id: UUID
    previous_key_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    new_key_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
