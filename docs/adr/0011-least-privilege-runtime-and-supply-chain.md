# ADR 0011: Add least-privilege runtime and supply-chain controls

- Status: Accepted
- Date: 2026-08-24

## Context

Client-side MQTT authentication and hardened pod security do not define what an identity
may publish or subscribe to, and they do not restrict pod network destinations. Mutable
container tags and an unscanned application image also weaken release reproducibility.

## Decision

- Configure the bundled Mosquitto broker with separate simulator and consumer identities.
- Grant the simulator write access only to its exact machine telemetry topic and grant the
  consumer read access only to telemetry plus the broker-version health topic.
- Keep the local broker loopback-only and clearly classify its documented passwords and
  plaintext transport as development-only.
- Add default-deny Kubernetes ingress and egress policy, then allow DNS, monitoring ingress,
  broker egress on 8883, and database egress on 5432 for the selected workloads.
- Pin base and third-party Compose images to immutable multi-platform manifest digests.
- Pin the Trivy GitHub Action to a full commit and make CI reject actionable high or
  critical vulnerabilities with an available fix in the built consumer image.

## Consequences

- A compromised local publisher cannot publish as another configured machine, and the
  consumer cannot publish telemetry.
- Network policy requires a CNI implementation that enforces `NetworkPolicy`.
- Standard Kubernetes policy cannot select external services by DNS name. The committed
  baseline limits ports but uses broad IPv4 destinations; production overlays must narrow
  destination CIDRs or use a CNI with FQDN-aware policy.
- Digest pins improve reproducibility but require deliberate dependency update work.
- Findings without an upstream fix remain visible during full operator scans but do not
  make every CI run permanently unactionable. Vulnerability scanning reduces known
  exposure; it does not replace patching, provenance attestations, runtime controls, or
  review of application logic.
