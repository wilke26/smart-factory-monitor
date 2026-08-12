# ADR-0001: MQTT for telemetry transport

- Status: Accepted
- Date: 2026-08-12

## Context

Machines must publish measurements independently of later consumers. The first release
needs a lightweight, locally reproducible event transport with topic-based routing.

## Decision

Use MQTT 5 with Eclipse Mosquitto as broker and Paho MQTT as the Python client. Publish
telemetry with QoS 1 to `factory/{area}/{machine_id}/telemetry`.

## Consequences

- Publishers and consumers can evolve independently.
- Topic hierarchy supports area- or machine-level subscriptions.
- QoS 1 means future consumers must tolerate duplicates.
- Broker operations, authentication and TLS become explicit production concerns.
