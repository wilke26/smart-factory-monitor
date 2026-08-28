# ADR 0020: Reproducible build and immutable release inputs

- Status: accepted
- Date: 2026-08-28

## Context

Version ranges in `pyproject.toml` express compatibility but allow two builds of the same
commit to resolve different transitive packages. Action tags can be moved, and a
Kubernetes image tag can resolve to different bytes after approval. Existing digest pins
for base and third-party service images did not close those three remaining input paths.

## Decision

Maintain separate, hash-pinned lockfiles for wheel-building tools, the non-ML runtime, the
ML runtime, and development/CI. Docker uses a locked builder stage, installs runtime
dependencies with `--require-hashes`, installs the locally built wheel without dependency
resolution, verifies the environment, and removes `pip` from the final image. CI installs
the development lock, regenerates every lock on Python 3.12, and rejects drift.

Pin every external GitHub Action to a full 40-character commit while retaining the
reviewed release version in a comment. Release automation must render the Azure overlay
through `deploy/kubernetes/render-release.py`, which accepts only a validated registry
repository plus a lowercase SHA-256 digest and verifies that all three application
deployments use the resulting immutable reference.

Committed Kubernetes tags remain readable development templates. They are not accepted
as production release evidence.

## Consequences

- Rebuilding a commit consumes explicitly reviewed Python artifacts and action code.
- Runtime and ML images do not resolve dependencies during application installation.
- Production rollout manifests bind consumer, simulator, and dispatcher to identical
  image bytes.
- Dependency updates become larger reviewed lockfile changes and lock regeneration adds
  CI time.
- Platform packages installed by the base image and Debian repositories are still an
  external build input; image scanning, periodic rebuilds, and registry-bound image
  provenance remain necessary.
