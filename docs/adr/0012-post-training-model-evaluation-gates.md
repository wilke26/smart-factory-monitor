# ADR 0012: Gate models with post-training anomaly rate and feature drift

- Status: Accepted
- Date: 2026-08-25

## Context

A valid signature proves who produced an artifact and that its bytes were not modified. It
does not establish that the model behaves acceptably on data outside its training window.
Evaluating the same rows used to fit the estimator would provide misleading evidence, and
automatically promoting a passing local file would combine quality assessment with a
deployment authority this repository does not have.

## Decision

Extend the signed Isolation Forest artifact format to version 2 and store decile-derived
bin edges plus training proportions for each feature. Add a separate offline evaluation
command that verifies the artifact before deserialization and loads only bounded telemetry
whose event timestamp is later than the maximum timestamp in the artifact's training set.

For every configured machine, calculate the model anomaly rate and Population Stability
Index for each feature. Apply three explicit gates: minimum sample count, maximum anomaly
rate, and maximum feature PSI. Report every machine in structured logs, then return a
failure status if any gate failed. Do not modify, activate, or promote artifacts.

## Consequences

- No row used for training can also satisfy the post-training evaluation query.
- Drift thresholds use the exact reference bins authenticated with the model.
- CI and release automation receive one deterministic pass/fail boundary.
- PSI detects distribution change but not accuracy, causality, or equipment failure.
- Late rows at or before the training boundary are excluded from post-training evidence.
- Format-v1 artifacts are rejected and require explicit retraining.
- Durable reports, labelled evaluation, immutable promotion, and rollback remain external
  lifecycle responsibilities.
