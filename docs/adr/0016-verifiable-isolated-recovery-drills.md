# ADR 0016: Create verifiable backups and restore only into isolated targets

- Status: Accepted
- Date: 2026-08-27

## Context

The database, active model-registry manifest, immutable model versions, detached
signatures, and verification public key together form the recoverable application state.
Docker volume persistence alone is not a backup, and an untested dump does not establish
recoverability. Restoring directly over active state would make a routine recovery drill
destructive.

The offline signing private key has a different custody and recovery lifecycle. Copying it
into an application backup would weaken that boundary.

## Decision

Create a versioned backup bundle containing a PostgreSQL custom-format dump, a compressed
model-registry archive, the public verification key, format metadata, and SHA-256 checksums
for every payload. Write the bundle through a private partial directory and publish it only
with one final rename. Reject reused or unsafe backup identifiers.

Before restore, verify every checksum, the declared format and identity, and reject model
archives containing absolute paths, parent traversal, links, or special files. Restore the
database under an explicit name that must differ from the active database. Restore the
registry and public key only into dedicated recovery volumes. Never overwrite the active
database or active model volume through the Compose recovery workflow.

CI performs a complete recovery drill after ingestion, evaluation, promotion, and alert
creation. It compares row counts for all application evidence tables and migration history,
then loads the restored registry through the normal digest, signature, identity, and model
compatibility checks.

## Consequences

- Backup integrity and application-level restorability are exercised continuously.
- Recovery tests are non-destructive and can run beside the development stack.
- The bundle contains no database password, webhook credential, MQTT credential, or
  signing private key.
- Operators must quiesce model writers while creating a bundle. PostgreSQL provides a
  consistent dump snapshot, but the filesystem registry has no cross-store transaction.
- Production deployments still need encrypted off-site storage, access control, retention,
  scheduled execution, restore objectives, managed-database procedures, and separate
  private-key disaster recovery.

## Implementation note (v0.14.1)

TimescaleDB hypertable constraints must be recreated while `timescaledb_pre_restore()` is
active, while application foreign keys that reference restored hypertable rows must be
validated after `timescaledb_post_restore()`. The restore therefore preserves the dump TOC
ordering but performs two passes: all non-foreign-key entries in restore mode, followed by
only foreign-key entries in normal mode. The exit trap always calls `post_restore` if the
first pass fails, so a failed drill cannot leave TimescaleDB background workers disabled.
