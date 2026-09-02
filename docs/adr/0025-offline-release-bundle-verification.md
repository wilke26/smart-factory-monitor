# ADR 0025: Offline complete release-bundle verification

- Status: accepted
- Date: 2026-09-02

## Context

v0.22 publishes a checksummed schema-3 manifest, packages, two encrypted SBOMs, and a
digest-bound Kubernetes manifest. Individual commands can check hashes, pull the image,
or decrypt one SBOM, but that procedure leaves important cross-file invariants to a human:
exact membership, release identity, shared recipient, container identity, and complete
deployment binding. It also makes independent recovery unnecessarily error-prone.

The downloaded release directory and every value inside it must be treated as untrusted.
Verification must not require GitHub, a registry, Sigstore, or access to private material.

## Decision

Provide `smart-factory-verify-release` as an installed command backed by the reusable
`smart_factory.release_verification` module.

1. Basic verification uses only the Python standard library and performs no network
   access. It requires exactly the seven files defined by manifest schema 3 and rejects
   directories, symbolic links, special files, path components, duplicate checksum
   entries, and additional content.
2. Validate version-derived filenames, media types, sizes, SHA-256 records, `SHA256SUMS`,
   release version and revision, supported platform, canonical qualified image plus full
   digest, both authenticated encryption envelopes, and one shared recipient fingerprint.
3. Parse the rendered YAML conservatively and require exactly three Deployments whose
   image fields all equal the manifest's digest-qualified container reference.
4. Allow operators to pin expected version, revision, and image reference. A mismatch is
   a verification failure even when the bundle is internally self-consistent.
5. Optionally match an external RSA public key or decrypt both SBOMs with an external
   private key. Cryptography is imported only for those modes. Recovery uses a mode-0700
   temporary directory and validates plaintext hash, SPDX 2.x identity, and package count
   before automatic deletion.
6. Emit concise human output by default, stable JSON on request, and a nonzero process
   exit for every invalid or unsupported input.
7. Run the same verifier in the unprivileged release-assembly job before evidence is
   transferred to attestation or publication jobs.

The digest-only admission expression is also aligned with the release renderer and
verifier: an image must contain a qualified repository path, so a bare
`application@sha256:...` reference is rejected.

## Consequences

- A retained bundle can be checked without trusting GitHub availability or reproducing
  the build environment.
- External key custody remains optional for public metadata verification and mandatory
  only when private dependency inventories must be recovered.
- The command validates the evidence that exists; it does not prove registry availability,
  artifact provenance, tag ancestry, vulnerability status, or immutable off-site
  retention. Those remain separate release and operational controls.
- Strict membership deliberately rejects forward schema additions until the verifier is
  updated to understand them.

## Rejected alternatives

- Keep a multi-command runbook only: it is easy to omit a cross-file invariant and hard to
  automate consistently.
- Require the private key for every verification: checksum and identity checks should be
  available to reviewers who must not receive recovery authority.
- Fetch release or registry data inside the verifier: offline verification would then
  inherit external availability, authentication, and substitution risks.
- Extract private SBOMs into the release directory: persistent plaintext would weaken the
  privacy boundary and complicate secure cleanup.
