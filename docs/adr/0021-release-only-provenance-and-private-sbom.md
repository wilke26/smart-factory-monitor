# ADR 0021: Release-only provenance and private SBOM

- Status: accepted
- Date: 2026-08-28

ADR 0022 supersedes the ephemeral-retention part of this decision by encrypting the exact
SBOM and retaining the ciphertext as a durable release asset. The release-only and
non-publication boundaries remain in force.

## Context

Reproducible inputs do not by themselves prove which workflow produced a downloadable
artifact. GitHub artifact attestations can bind artifacts to a repository, revision, and
workflow identity. A complete software bill of materials is also useful for vulnerability
response, but it exposes the exact dependency inventory. If the repository becomes public,
new GitHub attestations use public Sigstore infrastructure and its transparency record is
not a revocable private artifact store.

Attesting every push would mix intermediate commits with deliberate releases and could
publish dependency details for builds nobody consumes. The release boundary must therefore
separate internal inventory verification from externally discoverable provenance.

## Decision

Run the supply-chain job only for tags shaped as `vMAJOR.MINOR.PATCH`. The tag must exactly
match the package version, and both the Python quality matrix and the full Compose job must
succeed first.

Build the wheel and source archive from locked inputs. Assemble the complete ML runtime in
an isolated runner directory, create an SPDX JSON SBOM with a commit-pinned action and fixed
Syft version, and reject an invalid or empty document. Do not upload that SBOM, attach it to
a release, or submit it as an SBOM attestation.

Create a deterministic manifest containing artifact digests, sizes, revision, SBOM digest,
scope, format, and package count. GitHub build provenance covers the wheel, source archive,
and manifest through their checksum file when the repository is public. A private Enterprise
Cloud repository may explicitly opt in with `ENABLE_GITHUB_ATTESTATIONS=true`; other private
plans skip the unsupported attestation without losing the release evidence. Retain the
release artifacts and, when created, the provenance bundle for 30 days. The SBOM may be
retained separately under an environment-specific access and retention policy; its digest
reconnects it to the release manifest.

Do not push a container image in this workflow. Container provenance remains a distinct
registry-bound release decision.

## Consequences

- Ordinary branch pushes and pull requests create no external attestations.
- A release tag is an explicit publication decision and fails closed on a version mismatch
  or failed quality/Compose gate.
- Private Free, Pro, and Team repositories retain checksummed evidence without attempting an
  unsupported GitHub attestation; private Enterprise Cloud use requires explicit opt-in.
- Consumers can verify the package provenance and checksums without receiving the complete
  dependency inventory.
- The project still produces a full runtime SBOM for structural validation and private
  retention, but CI deliberately discards it when the runner ends.
- If the repository becomes public, operators must treat each new release attestation as a
  permanent public transparency event and review the release contents before tagging.
- Package provenance alone does not establish container provenance; ADR 0023 adds a
  separately identified and optionally attested registry digest.
