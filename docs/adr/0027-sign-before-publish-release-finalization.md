# ADR 0027: Sign-before-publish release finalization

- Status: accepted
- Date: 2026-09-02

## Context

v0.24 signs a complete release bundle with an externally controlled Ed25519 key. The
signing command verifies internal consistency, but it derives the authorized version,
revision, and container reference from the same downloaded bundle it is about to sign.
A careful operator can run a separate verification command with expected values first,
yet that two-command sequence leaves an avoidable validation-to-use gap and permits an
omitted or stale manual expectation.

The v0.24 workflow also publishes seven unsigned assets before the operator adds the
eighth signature asset. That sequence is incompatible with a release policy that prevents
asset mutation immediately after publication.

## Decision

1. Require `expected_version`, `expected_revision`, and
   `expected_image_reference` in the release-signing API and command line. Pass all three
   into the full offline verifier in the same process before loading and using the signing
   private key.
2. Keep destination creation write-once. A failed identity check must not create a
   signature file.
3. Change the tag-triggered GitHub workflow to create an unsigned draft release containing
   the seven internally verified assets. It must not publish that draft.
4. In the controlled operator environment, download the draft, obtain the expected commit
   from the trusted annotated tag and the expected image reference from an independently
   reviewed release decision, then sign with all three expectations.
5. Upload the detached signature to the draft. Download all eight assets into a new
   directory and verify them with the independent public key. During an exclusive
   finalization window, re-upload exactly that verified set, perform a second readback,
   and require the remote annotated tag still to resolve to the signed revision before
   publishing the draft.
6. Fail closed on platforms that cannot open snapshot inputs without following symbolic
   links.
7. Enable repository-level immutable releases before final publication where the GitHub
   repository plan supports that control. Treat independently administered immutable
   off-site retention as a separate production requirement.

## Consequences

- A self-consistent attacker-supplied bundle cannot choose the identity that the external
  operator authorizes during signing.
- Consumers never need to observe an intentionally unsigned public release.
- The full public asset set can be immutable from its first published state.
- Release completion becomes an explicit operator ceremony after the tag workflow rather
  than a fully automatic publication.
- GitHub asset upload and draft publication remain separate API operations. Tag protection,
  restricted release writers, immediate pre-publication readback, and consumer-side
  signature verification remain necessary; the client cannot create a server-side atomic
  transaction across these operations.
- GitHub remains the primary availability location until an independent mirror is added.

## Rejected alternatives

- Keep the separate preflight verification: it does not make the authorization target
  mandatory or close the validation-to-signing interval.
- Publish first and lock later: consumers may observe or retrieve an incomplete release.
- Put the external signing key in CI: this would collapse the independent trust boundary.
- Read expected identity only from the release manifest: that repeats the untrusted claim
  rather than expressing the operator's authorization decision.
