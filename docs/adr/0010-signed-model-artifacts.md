# ADR 0010: Verify signed ML artifacts before deserialization

- Status: Accepted
- Date: 2026-08-24

## Context

Joblib model artifacts use pickle-compatible deserialization. Structural validation after
loading cannot prevent malicious pickle instructions from executing. Treating a writable
model volume as trusted is therefore too weak for a deployment boundary.

## Decision

- Generate a dedicated Ed25519 key pair outside the model registry.
- Give the offline trainer the private signing key and the online consumer only the public
  verification key.
- Sign the exact serialized artifact bytes and store a detached `.joblib.sig` file.
- Verify the signature over bytes read once into memory before calling `joblib.load` on
  those same bytes.
- Fail closed on missing, malformed, mismatched, or invalid keys and signatures.
- Keep existing format, machine identity, feature-order, estimator, and library-version
  validation after cryptographic verification.

## Consequences

- Corrupted or untrusted artifacts cannot reach pickle deserialization without possession
  of the signing key.
- Reading once before verification removes a verify-then-reopen race.
- Private-key access is limited to key initialization and offline training; the consumer
  deployment mounts only the public key.
- Signing proves integrity and origin under the trusted key. It does not provide model
  quality evaluation, human approval, freshness, rollback, or key rotation by itself.
- Compromise of the signing key requires replacement of both keys and re-signing approved
  artifacts.
