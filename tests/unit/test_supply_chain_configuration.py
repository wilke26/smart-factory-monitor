from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_FILES = ("build.lock", "runtime.lock", "ml.lock", "dev.lock")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def test_dependency_locks_use_exact_versions_and_hashes() -> None:
    for name in LOCK_FILES:
        content = (REPOSITORY_ROOT / "requirements" / name).read_text(encoding="utf-8")
        requirement_starts = [
            match.start() for match in re.finditer(r"(?m)^[a-z0-9][a-z0-9._-]*==", content)
        ]
        assert requirement_starts, f"{name} contains no pinned requirements"
        requirement_starts.append(len(content))

        for start, end in pairwise(requirement_starts):
            block = content[start:end]
            assert "--hash=sha256:" in block, f"unhashed requirement in {name}: {block!r}"


def test_github_actions_are_pinned_to_full_commits() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    references = re.findall(r"(?m)^\s*-?\s*uses:\s+([^\s#]+)", workflow)
    assert references

    for reference in references:
        if reference.startswith("./"):
            continue
        _, separator, revision = reference.rpartition("@")
        assert separator and FULL_COMMIT.fullmatch(revision), reference


def test_release_evidence_is_restricted_to_trusted_release_tags() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    release_build_job = workflow.split("  release-build:", maxsplit=1)[1].split(
        "\n  release-attest:", maxsplit=1
    )[0]
    assert "if: startsWith(github.ref, 'refs/tags/v')" in release_build_job
    assert "needs: [quality, compose]" in release_build_job
    assert 'tag_ref="refs/tags/${GITHUB_REF_NAME}"' in release_build_job
    assert 'if [ "${GITHUB_REF_NAME}" != "${expected_tag}" ]; then' in release_build_job
    assert 'tag_type=$(git cat-file -t "${tag_ref}" 2>/dev/null || true)' in release_build_job
    assert 'release_commit=$(git rev-parse "${tag_ref}^{commit}")' in release_build_job
    assert '"refs/heads/main:refs/remotes/origin/main"' in release_build_job
    assert 'git merge-base --is-ancestor "${release_commit}"' in release_build_job
    assert "Release version mismatch" in release_build_job
    assert "Untrusted release tag" in release_build_job
    assert "Release is not on main" in release_build_job
    assert "RELEASE_EVIDENCE_RECIPIENT_PUBLIC_KEY" in release_build_job
    assert "release_evidence_crypto.py encrypt" in release_build_job
    assert "--encrypted-sbom" in release_build_job
    assert "${RUNNER_TEMP}/smart-factory-ml-runtime" in release_build_job
    assert "upload-artifact: false" in release_build_job
    assert "upload-release-assets: false" in release_build_job
    assert "retention-days: 1" in release_build_job
    assert "attestations: write" not in release_build_job
    assert "id-token: write" not in release_build_job
    assert "contents: write" not in release_build_job


def test_attestation_and_publication_use_isolated_permissions() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    attest_job = workflow.split("  release-attest:", maxsplit=1)[1].split(
        "\n  release-publish:", maxsplit=1
    )[0]
    publish_job = workflow.split("  release-publish:", maxsplit=1)[1].split(
        "\n  compose:", maxsplit=1
    )[0]

    assert "needs: release-build" in attest_job
    assert "attestations: write" in attest_job
    assert "id-token: write" in attest_job
    assert "contents: write" not in attest_job
    assert "github.event.repository.visibility == 'public'" in attest_job
    assert "vars.ENABLE_GITHUB_ATTESTATIONS == 'true'" in attest_job
    assert "subject-checksums: dist/SHA256SUMS" in attest_job
    assert "python -m build" not in attest_job
    assert "anchore/sbom-action" not in attest_job

    assert "needs: [release-build, release-attest]" in publish_job
    assert "needs.release-build.result == 'success'" in publish_job
    assert "needs.release-attest.result == 'success'" in publish_job
    assert "needs.release-attest.result == 'skipped'" in publish_job
    assert "contents: write" in publish_job
    assert "id-token: write" not in publish_job
    assert "attestations: write" not in publish_job
    assert 'gh release create "${GITHUB_REF_NAME}"' in publish_job
    assert "sha256sum --check SHA256SUMS" in publish_job
    assert "Durable encrypted release evidence was published" in publish_job
    assert "retention-days: 30" not in publish_job
    assert "sbom-path:" not in workflow
    assert "push-to-registry: true" not in workflow


def test_container_installation_enforces_hash_locks() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("--require-hashes") == 2
    assert "requirements/build.lock" in dockerfile
    assert "requirements/runtime.lock" in dockerfile
    assert "pip install --upgrade" not in dockerfile


def test_release_recovery_material_is_excluded_from_source_and_build_context() -> None:
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")

    for ignored_name in (
        "release-evidence-private.pem",
        "release-evidence-public.pem",
        "recovered*.spdx.json",
    ):
        assert ignored_name in gitignore
        assert ignored_name in dockerignore
