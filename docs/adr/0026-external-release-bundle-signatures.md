# ADR 0026: Externally anchored release-bundle signatures

- Status: accepted
- Date: 2026-09-02

## Context

v0.23 verifies that a downloaded schema-3 release bundle is complete and internally
consistent. SHA-256 checksums detect accidental or partial modification, but an attacker
who can replace every release asset could also create a new manifest and checksum file.
GitHub artifact attestations provide an authenticity layer only where the repository plan
supports them and remain coupled to GitHub availability and identity.

The existing external RSA key exists solely to keep SBOM contents confidential. Reusing
one key for both encryption and signing would mix responsibilities and enlarge the impact
of a compromise. Giving a new signing private key to GitHub Actions would also collapse
the independent trust boundary this decision is intended to create.

## Decision

1. Use a dedicated Ed25519 signing key generated in the controlled operator environment.
   Encrypt its PKCS#8 private-key bytes with a password supplied only through an
   environment variable. Never provide the private key or password to GitHub Actions.
2. Sign only after GitHub has published the ordinary release. The signing command first
   performs the full v0.23 offline bundle verification and refuses to overwrite an
   existing key or signature file.
3. Create one detached canonical JSON document named
   `smart_factory_monitor-<version>.release-signature.json`. Its signed payload contains
   the product, semantic version, full Git revision, digest-qualified container reference,
   SHA-256 of `SHA256SUMS`, SHA-256 of `release-manifest.json`, algorithm, schema version,
   and signing-public-key fingerprint.
4. Upload the signature document as an eighth public release asset. It is intentionally
   absent from `SHA256SUMS`: signing the checksum file covers the original evidence
   transitively without creating a self-referential checksum/signature cycle.
5. Extend `smart-factory-verify-release` with paired `--signature` and
   `--signing-public-key` options. Only this explicit mode permits the eighth asset. Verify
   the independently obtained Ed25519 public key, exact payload, and signature offline.
6. Keep cryptography optional under the `release-evidence` package extra. Unsigned bundle
   verification remains standard-library-only and network-independent.

## Consequences

- Recalculating all internal bundle checksums no longer hides replacement from an operator
  who requires the external signature and trusts the independently distributed public
  key.
- The private signing key becomes high-value offline material requiring backup, access
  control, password custody, rotation, and eventual revocation policy.
- The signature is a post-publication operator action. Until it is uploaded, the release
  has internal integrity evidence but not this independent authenticity anchor.
- GitHub can store the public signature document without gaining the authority to create a
  valid replacement.
- The design does not yet automate immutable off-site mirroring or signing-key rotation.

## Rejected alternatives

- Treat `SHA256SUMS` as an authenticity proof: hashes alone do not identify their author.
- Reuse the RSA SBOM-recipient key: encryption and signing need separate compromise and
  rotation domains.
- Store the Ed25519 private key in GitHub Actions: this would make the independent anchor
  vulnerable to the same release-system compromise.
- Add the signature to the checksum file: the signature would then have to sign a checksum
  of itself.
- Silently ignore a detached signature during basic verification: consumers could mistake
  an unverified extra file for authenticated evidence.
