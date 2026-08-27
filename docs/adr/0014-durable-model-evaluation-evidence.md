# ADR 0014: Persist immutable model-evaluation evidence

- Status: Accepted
- Date: 2026-08-26

## Context

The offline evaluator previously emitted complete structured logs, but a one-shot
container does not itself provide durable, queryable release evidence. Treating log
collection as the only audit record also makes deployment gates depend on external log
retention that the application cannot verify.

## Decision

Represent one model evaluation as a transport-neutral, immutable domain record and expose
persistence through a narrow `ModelEvaluationStore` port. Store each machine result in
`model_evaluation_runs` before logging it or reporting its gate outcome. Persist the signed
artifact identity and exact SHA-256, training boundary, sample count, anomaly rate, per-feature PSI,
maximum PSI, pass/fail decision, and stable failed-gate names under a unique evaluation
UUID.

Use a normal PostgreSQL table rather than a hypertable: evaluation records are low-volume
audit evidence, not machine-frequency time series. Persistence failure fails the evaluator
closed. A failed gate is still valid evidence and is stored before the command aggregates
machine failures and exits unsuccessfully.

## Consequences

- Evaluation history survives the evaluator container and can be queried by machine,
  model, or time.
- Gate calculation remains independent of PostgreSQL and can be tested through the port.
- Release automation cannot accept a result that was only logged but not persisted.
- Multiple evaluations of the same model remain separate audit events by design.
- v0.13 uses the exact artifact digest as part of its promotion authorization check.
- Evidence proves what the configured gates decided; it does not approve or promote a
  model and does not provide labelled accuracy.
- Retention, archival, access control, and external attestation of audit records remain
  operational policy.
