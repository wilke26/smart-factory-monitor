# ADR 0005: Start anomaly detection with deterministic rules

- Status: Accepted
- Date: 2026-08-13

## Context

Known unsafe or inefficient operating conditions must be detected immediately and be
explainable to production staff. Machine learning would add training data, evaluation,
drift, and operational complexity before a problem requires it.

## Decision

Implement independent rules for high temperature, vibration, and power plus low
production rate. Keep the detector as a pure domain service. Persist each finding with
the observed value, threshold, comparison, severity, and message in the same transaction
as its source reading.

## Consequences

- Every decision is deterministic, testable, and auditable.
- Thresholds can be configured without coupling rules to transports or storage.
- Multiple simultaneous symptoms are retained.
- The system detects only conditions represented by explicit rules.
- A future ML detector can complement these rules rather than replace known safety
  constraints.
