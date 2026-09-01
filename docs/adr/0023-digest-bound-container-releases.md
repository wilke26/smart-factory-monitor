# ADR 0023: Digest-bound container releases

- Status: accepted
- Date: 2026-09-01

## Context

v0.20 made the Python packages and exact ML-runtime SBOM recoverable and optionally
attestable, but it did not publish or identify the container that operators actually run.
The Kubernetes release renderer already rejected mutable tags and required one digest for
all application deployments, yet that digest had to be supplied from an unrelated
registry process. Package provenance therefore stopped before the deployment boundary.

A release container contains a different dependency set from the wheel and must have its
own inventory. Registry publication also requires `packages: write`, which must not be
added to package building, attestation, evidence assembly, or GitHub Release publication.

## Decision

For an annotated release tag that passed the complete quality and Compose gates:

1. Keep `release-build` read-only. It builds the wheel and source archive and encrypts the
   ML-runtime SBOM exactly as in ADR 0022.
2. Run one `release-container` job with only `contents: read` and `packages: write`. Build
   one `linux/amd64` image with the complete hash-locked ML dependency set, scan that exact
   local image for actionable high and critical vulnerabilities, then publish only the
   version tag to `ghcr.io/<owner>/<repository>`.
3. Resolve the registry's canonical SHA-256 digest, pull the published image by that
   digest, and create the container SPDX SBOM from the digest reference. Encrypt the exact
   SBOM for the same externally controlled RSA recipient used for package evidence. Record
   the plaintext and ciphertext digests, package count, platform, image name, registry
   digest, and immutable reference in checksummed intermediate evidence.
4. Use a separate `release-assemble` job without registry, attestation, or release-write
   permission. Verify both intermediate transfers, render the Kubernetes deployment with
   the recorded image digest, and produce release-manifest schema 3. The final checksums
   cover wheel, source archive, both encrypted SBOMs, the digest-bound Kubernetes YAML,
   and the final manifest.
5. Where GitHub attestation is supported, attest both the checksummed release files and
   the published image name plus digest. Keep GitHub Release publication isolated with
   only `contents: write`.

The mutable registry tag is a discovery alias only. Deployment and verification must use
the digest in `release-manifest.json` or the attached Kubernetes manifest. Plaintext SBOMs
must never cross a job boundary or become registry, workflow, attestation, or release
assets.

## Consequences

- A release now binds source packages, one exact container manifest, its dependency
  inventory, and the Kubernetes deployment input into one checksummed evidence set.
- All three application deployments run the same image bytes. Their command and runtime
  configuration still select the simulator, consumer, and dispatcher roles.
- GHCR receives the image before later SBOM, assembly, or publication steps complete. A
  later failure can leave an unreferenced package version, but cannot create a GitHub
  Release or deployment manifest. Operators must investigate rather than overwrite that
  tag silently.
- The first release platform is deliberately `linux/amd64`. Multi-platform publication
  would require an OCI index, per-platform SBOMs, and explicit index-versus-manifest
  provenance semantics.
- A private GHCR package requires authenticated pull access. Kubernetes must use an
  appropriate image-pull identity or Secret, while deployment remains digest-based.
- GitHub's optional attestation availability and public-transparency implications remain
  as described in ADR 0021 and ADR 0022. The encrypted SBOM is retained regardless.
- Registry retention, tag immutability policy, replication, admission enforcement, and
  independently administered evidence mirroring remain production responsibilities.

## Rejected alternatives

- Build a second container in the publication job: the tested image and published image
  could differ.
- Deploy the semantic version tag: registry tags are mutable and cannot identify bytes.
- Publish a plaintext container SBOM: exposes a version-specific vulnerability inventory
  and conflicts with the established SBOM privacy boundary.
- Give the package-build or attestation job registry write access: combines unrelated
  authorities and increases release compromise impact.
- Treat package provenance as container provenance: the container includes its base image,
  operating-system packages, and installed runtime dependencies beyond the wheel.
