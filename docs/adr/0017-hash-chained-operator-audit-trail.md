# ADR 0017: Hash-chained operator audit trail

## Status

Accepted

## Context

Model evaluation evidence records what automated quality gates decided, but it does not
record who requested a privileged registry change or why. Structured process logs are
also insufficient as the authoritative record because their retention and mutability are
outside the command's control. Promotion and rollback modify filesystem registry state,
so an unavailable audit sink must stop the operation before that modification begins.

PostgreSQL and the model-registry filesystem cannot participate in one ACID transaction.
The design must therefore make interrupted cross-resource operations visible rather than
claiming atomicity that does not exist.

## Decision

Persist `started`, `succeeded`, and `failed` events for model promotion and rollback in
`operator_audit_events`. Every event records an explicit actor, reason or ticket,
correlation UUID, timestamp, action, outcome, previous state, resulting or intended state,
and bounded error type. The CLI requires this context and expects production automation to
inject an authenticated identity; the application does not authenticate a free-form
environment variable itself.

Serialize writers with a PostgreSQL transaction-scoped advisory lock. Each row stores the
previous event hash and a SHA-256 digest over that hash plus a canonical representation of
the complete event. A verification command recomputes the chain from the genesis value.
Reject `UPDATE` and `DELETE` through a database trigger so normal application access is
append-only.

Write `started` before evaluation checks or registry mutation. If that append fails, the
privileged operation fails closed. Write the terminal event after success or failure. If a
process crashes or the terminal append fails after filesystem publication, the unmatched
`started` event remains explicit evidence of an operation requiring reconciliation.

## Consequences

- Promotion and rollback cannot proceed while the audit database is unavailable.
- Concurrent command writers produce one deterministic chain order.
- Accidental or ordinary application-role mutation is rejected and offline tampering is
  detectable by chain verification.
- A database owner can still disable triggers and rewrite the complete chain. v0.16 adds
  signed external checkpoints to expose such a rewrite, while production still requires
  restricted ownership, scheduled immutable retention, access logging, archival, and
  deletion policy.
- Key rotation and security-relevant configuration changes do not yet have composition
  roots and remain future audit event types.
- Filesystem publication and audit completion are deliberately observable but not
  transactionally atomic across resources.
