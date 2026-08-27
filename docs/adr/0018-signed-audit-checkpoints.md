# ADR 0018: Externally retained signed audit checkpoints

## Status

Accepted

## Context

The v0.15 PostgreSQL trigger and SHA-256 chain reject ordinary mutation and detect changed
rows. A database owner can nevertheless disable the trigger, rewrite the complete table,
and calculate a new internally consistent chain. Detection therefore needs a trusted
historical chain head outside the database administrative boundary.

The evidence must be independently verifiable without restoring or contacting the source
database. It must also identify its deployment and signing key so a valid checkpoint from
another environment cannot be silently substituted.

## Decision

After recomputing the complete database chain, export a canonical checkpoint containing
schema version, checkpoint UUID, deployment-specific chain ID, UTC creation time, event
count, head hash, and SHA-256 fingerprint of a dedicated Ed25519 attestation public key.
Sign the canonical checkpoint bytes and store checkpoint plus base64 signature in one
self-contained JSON envelope.

Use a separate attestation key pair from model artifact signing. The exporter requires
database access and the private key. The verifier requires only the envelope, expected
chain ID, and public key. It confirms chain identity, key fingerprint, and signature.
Checkpoint publication uses a new path and refuses replacement of existing evidence.

Local Compose initializes development keys in dedicated volumes and writes checkpoints to
an ignored host directory. CI exports and verifies a real checkpoint, proves that altered
content is rejected, and uploads the original as a workflow artifact outside PostgreSQL.

## Consequences

- A retained checkpoint exposes a later full-chain rewrite whose historical prefix no
  longer reaches the signed head.
- Verification is portable and does not trust the live database or application role.
- A checkpoint proves only the observed prefix at one time; it cannot prove that later
  events exist or that exports occurred on schedule.
- Production must authenticate its chain ID, protect and rotate the attestation key,
  retain old public keys, schedule exports, monitor freshness, and use immutable external
  storage with an explicit retention policy.
- GitHub workflow artifact retention demonstrates the boundary but is not prescribed as
  the production evidence store.
