# ADR-0002: Anonymous broker access is local-development only

- Status: Superseded by ADR 0011
- Date: 2026-08-12

## Context

The v0.1 acceptance criterion is a one-command local demonstration. Requiring certificate
generation or secret provisioning would obscure the event-streaming slice being learned.

## Decision

Allow anonymous access on the Docker Compose broker. Document the configuration as unsafe
for shared or internet-accessible environments.

## Consequences

- Local startup remains frictionless.
- Port 1883 must not be exposed on an untrusted network.
- A production deployment must add TLS, per-client identity, authorization and managed
  secret/certificate rotation before use.
- v0.8 added client support and Kubernetes secret wiring. v0.9 supersedes the anonymous
  local decision with separate development identities and least-privilege topic ACLs.
