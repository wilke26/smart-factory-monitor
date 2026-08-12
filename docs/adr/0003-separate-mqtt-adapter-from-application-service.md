# ADR 0003: Separate the MQTT adapter from the application service

- Status: Accepted
- Date: 2026-08-12

## Context

MQTT messages contain transport details and untrusted bytes. Future telemetry may also
arrive from replay files, HTTP, or another event platform.

## Decision

The MQTT consumer owns subscription, topic interpretation, JSON decoding, Pydantic
validation, and rejection logging. It invokes the `TelemetryHandler` inbound port only
with a valid `TelemetryReading`. The application service owns the use case and imports
no MQTT or JSON packages.

## Consequences

Application behavior is independently testable and reusable across transports. MQTT
tests can focus on the trust boundary. The design adds one small protocol, but avoids
speculative repository, unit-of-work, and event-bus abstractions.

