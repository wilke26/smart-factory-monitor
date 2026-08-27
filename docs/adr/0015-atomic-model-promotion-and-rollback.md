# ADR 0015: Atomic model promotion and rollback

- Status: Accepted
- Date: 2026-08-27

## Context

Training previously replaced the same files consumed by online inference. Evaluation was
durable in v0.12, but its result was not cryptographically bound to the exact candidate
bytes and no controlled operation separated training from activation. A multi-machine
copy could also expose a partially updated model set to a restarting consumer.

## Decision

Training writes signed artifacts only to `candidates/`. Evaluation stores the exact
artifact SHA-256 with every result. Promotion verifies the candidate signature and
identity, requires a passed database record for the same machine, model ID, and digest,
then publishes content-addressed artifact and signature files under `versions/`.

Activate the complete machine set by atomically replacing one strict `active.json`
manifest. Archive every manifest by a unique generation UUID. The consumer loads only
versions referenced by the active manifest and rechecks their digest, signature, machine
identity, artifact format, feature order, estimator type, and runtime version.

Rollback is explicit: an operator supplies an archived generation UUID. All referenced
files are reverified before a new generation pointing to the earlier model set becomes
active. Rollback never mutates or deletes an old generation.

## Consequences

- Training and evaluation cannot activate a model by themselves.
- A failed or missing exact-artifact evaluation rejects the complete promotion batch.
- One atomic manifest replacement prevents mixed multi-machine generations at startup.
- Content-addressed signed files and archived manifests provide deterministic rollback.
- The consumer requires an active manifest; legacy root-level artifacts must pass the new
  evaluation and promotion flow before ML-enabled startup.
- Registry write access, manifest archival/retention, human approval, and coordinated
  consumer rollout remain deployment responsibilities.
