# ADR 0009: Require verified MQTT transport in the Kubernetes baseline

- Status: Accepted
- Date: 2026-08-24

## Context

The original loopback-only Compose broker was anonymous and unencrypted. A shared or
cloud deployment needs broker identity verification, separate client identities, external
secret handling, and workload hardening. Embedding a development broker or credentials in
application manifests would blur that responsibility.

## Decision

- Support optional MQTT username/password, verified TLS, a private CA, and paired mTLS
  client certificate/key configuration in both MQTT adapters.
- Reject incomplete credential or certificate settings before connecting and provide no
  insecure certificate-verification bypass.
- Keep local Compose loopback-only; ADR 0011 subsequently adds development credentials and
  broker-side topic ACLs while retaining plaintext transport locally.
- Deploy application workloads to Kubernetes as fixed non-root users with read-only root
  filesystems, dropped capabilities, resource bounds, probes, and no service-account token.
- Reference external runtime and TLS Secrets; never commit secret values or certificates.
- Treat MQTT, TimescaleDB, schema migration, PKI, and secret rotation as deployment-owned
  prerequisites.

## Consequences

- The same application image can connect to managed or self-hosted secure brokers.
- Publisher and consumer deployments can map different Secret keys to the same environment
  variable names, enabling separate broker identities and ACLs.
- The manifests are a secure deployment baseline, not complete cloud infrastructure.
- ADR 0011 adds explicit ACL behavior to the bundled broker. Equivalent shared-broker ACL
  provisioning, certificate issuance/rotation, database migration automation, and
  managed-service lifecycle remain operator responsibilities.
