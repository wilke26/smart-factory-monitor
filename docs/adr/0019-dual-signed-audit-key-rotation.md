# ADR 0019: Dual-signed audit-attestation key rotation

- Status: Accepted; root storage amended by ADR 0028
- Date: 2026-08-27

## Context

ADR 0018 introduced externally retained checkpoints signed by a dedicated Ed25519 key.
Keeping one private key forever increases exposure, but simply replacing its public key
would create a new, unauthenticated trust root and could make historical checkpoints
unverifiable. The rotation itself is privileged and must leave evidence in the existing
operator audit chain.

## Decision

The first attestation key establishes a root fingerprint. Normal rotation creates an
immutable transition containing the deployment chain ID, both key fingerprints, a UUID,
and an aware timestamp. Its canonical representation is signed independently by the
previous and replacement private keys. The replacement public key and transition are
published before the active key changes. The replacement private key is first written to
a mode-0600 pending file and is atomically moved to the active path only after public
activation, so an interrupted operation retains enough secret material for explicit
operator reconciliation.

Verification starts from an explicitly configured root fingerprint, validates each
archived public key against its fingerprint, and walks only dual-signed transitions for
the expected deployment chain. Forks, cycles, missing links, excessive input, modified
keys, and invalid signatures fail closed. Checkpoint verification selects the archived
key named by the checkpoint only after this trust-chain validation.

Rotation is exposed as a separate operator command. It writes a `started` audit event
before filesystem mutation and a terminal `succeeded` or `failed` event afterward. Actor,
reason, and correlation ID remain mandatory. Migration 007 extends the database-enforced
action vocabulary with `audit_attestation_key_rotation`.

The v0.17.1 correction acquires an exclusive lock stored in the writable keyring before
reading the active key and retains it through the terminal audit event. The active key
must resolve through the verified transition path from the pinned root and match the
deployed public key before a new rotation can start.

## Consequences

- Historical and new checkpoints remain verifiable from one stable trust anchor.
- Concurrent rotation commands are serialized and cannot publish sibling transitions
  from the same active key.
- A broken existing root-to-active path prevents mutation instead of being discovered
  only by a later checkpoint verification.
- Possession of only the new key cannot authorize its insertion into an existing chain;
  the previous key must also sign the transition.
- Every referenced public key and transition must be retained for the evidence lifetime.
- A root change is a new trust domain, not an ordinary rotation.
- Database audit writes and filesystem publication cannot form one atomic transaction.
  A partial rotation is detectable through its non-terminal or failed audit evidence and
  requires operator reconciliation before retry.
- Local Compose stores the root fingerprint beside the public keyring for usability under
  the explicit development switch defined by ADR 0028. Production verification and
  rotation require the fingerprint value from independently controlled configuration, so
  replacing the entire keyring cannot replace its claimed root.
- Automated scheduling, external immutable retention, HSM/KMS-backed signing, separation
  of duties, and rotation approval remain deployment concerns.

## Rejected alternatives

- Trust only the current public key: loses historical continuity and permits silent root
  replacement.
- Sign the transition only with the old key: authorizes the fingerprint but does not
  prove possession of the replacement private key at rotation time.
- Sign only with the new key: any unrelated key could self-authorize.
- Store key history only in PostgreSQL: a database owner capable of rewriting the audit
  chain could rewrite the key history in the same administrative boundary.
