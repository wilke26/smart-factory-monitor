"""Immutable contracts for privileged operator audit events."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AuditValue = str | int | float | bool | None | tuple[str, ...]
AuditState = tuple[tuple[str, AuditValue], ...]


class OperatorAction(StrEnum):
    MODEL_PROMOTION = "model_promotion"
    MODEL_ROLLBACK = "model_rollback"


class OperatorActionOutcome(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperatorAuditContext(BaseModel):
    """Identity and justification supplied by trusted operator automation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    actor: Annotated[str, Field(min_length=1, max_length=255)]
    reason: Annotated[str, Field(min_length=1, max_length=2_000)]
    correlation_id: UUID

    @field_validator("actor", "reason")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("audit text must not have surrounding whitespace")
        return value


class OperatorAuditEvent(BaseModel):
    """One append-only state transition in a privileged operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: Annotated[str, Field(min_length=1, max_length=255)]
    reason: Annotated[str, Field(min_length=1, max_length=2_000)]
    correlation_id: UUID
    action: OperatorAction
    outcome: OperatorActionOutcome
    previous_state: AuditState = ()
    resulting_state: AuditState = ()
    error_type: Annotated[str, Field(min_length=1, max_length=255)] | None = None

    @classmethod
    def create(
        cls,
        context: OperatorAuditContext,
        *,
        action: OperatorAction,
        outcome: OperatorActionOutcome,
        previous_state: AuditState = (),
        resulting_state: AuditState = (),
        error_type: str | None = None,
    ) -> "OperatorAuditEvent":
        return cls(
            actor=context.actor,
            reason=context.reason,
            correlation_id=context.correlation_id,
            action=action,
            outcome=outcome,
            previous_state=previous_state,
            resulting_state=resulting_state,
            error_type=error_type,
        )

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit timestamp must include a UTC offset")
        return value

    @field_validator("previous_state", "resulting_state")
    @classmethod
    def state_keys_must_be_unique(cls, value: AuditState) -> AuditState:
        keys = [key for key, _ in value]
        if len(keys) != len(set(keys)):
            raise ValueError("audit state keys must be unique")
        return value

    @model_validator(mode="after")
    def error_type_must_match_outcome(self) -> Self:
        if self.outcome is OperatorActionOutcome.FAILED and self.error_type is None:
            raise ValueError("failed audit events require an error type")
        if self.outcome is not OperatorActionOutcome.FAILED and self.error_type is not None:
            raise ValueError("only failed audit events may include an error type")
        return self


class AuditChainVerification(BaseModel):
    """Result of independently recomputing the persisted audit hash chain."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    valid: bool
    event_count: int = Field(ge=0)
    head_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    invalid_sequence_number: int | None = Field(default=None, ge=1)
