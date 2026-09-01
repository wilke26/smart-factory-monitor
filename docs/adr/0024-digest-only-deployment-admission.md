# ADR 0024: Digest-only deployment admission

- Status: accepted
- Date: 2026-09-01

## Context

v0.21 binds the release container, encrypted container inventory, release manifest, and
rendered Kubernetes workloads to one registry digest. That evidence proves what the
release process intended to deploy, but a cluster administrator or automation error could
still submit a mutable tag directly to the Kubernetes API and bypass the renderer.

Kubernetes provides the stable `admissionregistration.k8s.io/v1`
`ValidatingAdmissionPolicy` API from version 1.30. It evaluates CEL in the API server and
does not require another webhook service or a third-party policy controller.

## Decision

Provide a cluster-scoped validating admission policy and binding as a separately installed
production prerequisite:

1. Match `CREATE` and `UPDATE` operations for every `apps/v1` Deployment in a namespace
   explicitly labelled `security.smart-factory-monitor.io/require-digest-images=true`.
2. Require every normal and init-container image to be a lowercase repository reference
   directly followed by a complete `@sha256:<64 lowercase hexadecimal characters>`
   digest. Reject semantic tags, tag-plus-digest forms, abbreviated digests, uppercase
   repositories, and unqualified mutable names.
3. Use `failurePolicy: Fail` and binding actions `Deny` plus `Audit`. A policy evaluation
   error therefore cannot silently allow a workload.
4. Label the dedicated Azure namespace to opt in. Scope through the namespace rather than
   a mutable Deployment label so a caller cannot bypass enforcement by removing an object
   label in the same request.
5. Install the policy and binding before the release namespace and workloads. Confirm
   admission activation with a server-side dry run that must reject a tagged image before
   applying the digest-bound release manifest.

The ordinary committed overlay retains a semantic tag for local rendering and review. It
is not an admissible production rollout once the namespace opts in; production continues
to use the digest-bound YAML attached to the corresponding release.

## Consequences

- A direct API request can no longer replace a v0.21-style digest reference with a mutable
  tag in an opted-in namespace.
- The policy also covers future sidecars and init containers in any Deployment in that
  namespace, preventing an unpinned auxiliary image from weakening the workload.
- Kubernetes 1.30 or newer is required for this production control. Policy installation is
  a cluster-administrator responsibility and is deliberately separate from application
  release permissions.
- `Deny` blocks the request and `Audit` exposes policy violations to the cluster audit
  pipeline when audit logging is configured.
- A digest identifies bytes but does not prove who built them. Signature or provenance
  verification, registry authorization, replicated retention, and admission for workload
  kinds other than Deployments remain separate controls.

## Rejected alternatives

- Rely only on the release renderer: callers can bypass it and submit arbitrary YAML.
- Select individual Deployments by an application label: a caller could omit the label on
  create and attempt to escape the policy scope.
- Install policy and workloads as one unordered release action: admission registration can
  take time to become active and would create a race for the first rollout.
- Add a policy-controller or image-verification webhook only for digest syntax: the native
  stable API provides the required fail-closed invariant with less operational surface.
- Accept tag-plus-digest references: the tag is redundant and obscures the digest-only
  operational contract.
