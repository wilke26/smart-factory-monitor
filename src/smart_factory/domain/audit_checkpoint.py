"""Immutable contracts for externally retained operator-audit checkpoints."""

from base64 import b64decode
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditCheckpoint(BaseModel):
    """A signed statement about one verified audit-chain head."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    checkpoint_id: UUID = Field(default_factory=uuid4)
    chain_id: Annotated[
        str,
        Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"),
    ]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_count: int = Field(ge=0)
    head_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    key_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("chain_id")
    @classmethod
    def chain_id_must_not_have_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("audit chain ID must not have surrounding whitespace")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit checkpoint timestamp must include a UTC offset")
        return value


class SignedAuditCheckpoint(BaseModel):
    """Self-contained checkpoint and its detached Ed25519 signature."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    checkpoint: AuditCheckpoint
    signature: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("signature")
    @classmethod
    def signature_must_be_canonical_base64(cls, value: str) -> str:
        try:
            decoded = b64decode(value, validate=True)
        except ValueError as error:
            raise ValueError("audit checkpoint signature must be base64") from error
        if len(decoded) != 64:
            raise ValueError("audit checkpoint signature must be an Ed25519 signature")
        return value
