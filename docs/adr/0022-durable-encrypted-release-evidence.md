# ADR 0022: Durable encrypted release evidence

- Status: accepted
- Date: 2026-08-31

## Context

ADR 0021 intentionally kept the complete ML-runtime SBOM out of workflow artifacts,
release assets, and public attestation. Its digest and package count survived in the
release manifest, but the exact SBOM bytes existed only on the ephemeral runner. For a
private repository without GitHub Enterprise Cloud, the remaining package evidence also
expired with the workflow artifact. A digest without recoverable source bytes is not
sufficient for later vulnerability response or evidentiary verification.

The tag-only job also held build, third-party SBOM generation, OIDC, attestation, and
artifact-metadata permissions in one security boundary. Release publication must preserve
SBOM confidentiality without granting signing or publication authority to build steps.

## Decision

Require an externally generated RSA recipient key of at least 3072 bits before a release
tag can complete. Store only its PEM public key in the GitHub Actions secret
`RELEASE_EVIDENCE_RECIPIENT_PUBLIC_KEY`; the corresponding private key and passphrase must
remain outside GitHub and outside the repository under the production recovery policy.

Encrypt the validated SBOM on the runner with a random AES-256-GCM data key. Bind its
filename, release version, and full Git revision as authenticated data, and wrap the data
key with RSA-OAEP-SHA256. The deterministic release manifest records both the plaintext
SBOM digest and the encrypted envelope's digest, size, algorithm, recipient public-key
fingerprint, and name. The plaintext
SBOM remains only in runner-temporary storage and is never transferred between jobs.

Split the release path into three jobs:

1. `release-build` has only repository read access. It requires an annotated semantic tag,
   verifies that the tag commit is an ancestor of `origin/main`, builds from locked inputs,
   creates and encrypts the SBOM, and transfers checksummed ciphertext for one day.
2. `release-attest` receives OIDC and attestation permissions only when GitHub attestation
   is supported. It downloads and verifies the already built evidence; it cannot publish a
   release or execute project build tooling.
3. `release-publish` receives only `contents: write`. It verifies the transferred checksums
   and creates a GitHub Release whose durable assets include packages, manifest, checksums,
   and the encrypted SBOM.

The recovery CLI refuses symlinked inputs, weak keys, release-identity mismatches,
authenticated-ciphertext modification, and output replacement. Decryption writes the
recovered SBOM with mode 0600. Release recovery must compare the recovered plaintext digest
with `release-manifest.json` and must remain part of operational drills.

## Consequences

- Exact SBOM bytes remain recoverable without becoming a public dependency inventory.
- A later repository visibility change exposes ciphertext, not the plaintext SBOM.
- Release evidence survives normal workflow-artifact expiration for the lifetime of the
  GitHub Release; independent immutable mirroring remains a production policy choice.
- A missing recipient public key fails a release tag instead of silently discarding the
  SBOM.
- The recorded recipient fingerprint identifies the required recovery key after key
  rotation. Losing the externally retained private key makes historical SBOMs unrecoverable. Key
  backup, access control, escrow, rotation, and recovery testing are mandatory operations.
- A tag outside `main`, a lightweight tag, a version mismatch, or a failed quality/Compose
  gate cannot publish release evidence.
- GitHub Release deletion or repository deletion can still remove the durable assets.
  Regulatory retention therefore requires an independently administered archive.
- ADR 0023 extends this package evidence with a separately authorized, digest-bound
  container publication, encrypted container SBOM, and Kubernetes deployment manifest.

## Rejected alternatives

- Retain only the SBOM digest: cannot reconstruct or prove the destroyed source bytes.
- Upload the plaintext SBOM to a private workflow artifact: time-bounded and vulnerable to
  later access or repository-visibility changes.
- Put the recipient private key in GitHub Actions: allows the same administrative boundary
  that creates the ciphertext to decrypt it.
- Give the release-build job attestation and publication permissions: unnecessarily expands
  the signing and release authority of dependency and third-party build steps.
