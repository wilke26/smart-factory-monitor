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
        "\n  release-container:", maxsplit=1
    )[0]
    assert "if: startsWith(github.ref, 'refs/tags/v')" in release_build_job
    assert "needs: [quality, compose]" in release_build_job
    assert 'tag_ref="refs/tags/${GITHUB_REF_NAME}"' in release_build_job
    assert 'verified_tag_ref="refs/release-tags/${GITHUB_REF_NAME}"' in release_build_job
    assert 'if [ "${GITHUB_REF_NAME}" != "${expected_tag}" ]; then' in release_build_job
    assert '"${tag_ref}:${verified_tag_ref}"' in release_build_job
    tag_type_check = 'tag_type=$(git cat-file -t "${verified_tag_ref}" 2>/dev/null || true)'
    assert tag_type_check in release_build_job
    assert 'release_commit=$(git rev-parse "${verified_tag_ref}^{commit}")' in release_build_job
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


def test_container_publication_and_evidence_assembly_use_isolated_permissions() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    container_job = workflow.split("  release-container:", maxsplit=1)[1].split(
        "\n  release-assemble:", maxsplit=1
    )[0]
    assemble_job = workflow.split("  release-assemble:", maxsplit=1)[1].split(
        "\n  release-attest:", maxsplit=1
    )[0]

    assert "needs: release-build" in container_job
    assert "packages: write" in container_job
    assert "contents: write" not in container_job
    assert "attestations: write" not in container_job
    assert "id-token: write" not in container_job
    assert container_job.count("docker build --pull --platform linux/amd64") == 1
    assert "DEPENDENCY_LOCK=requirements/ml.lock" in container_job
    assert "Authenticate and require an unused release tag" in container_job
    assert "Container tag already exists" in container_job
    assert "Registry lookup failed" in container_job
    assert "Scan exact release container before publication" in container_job
    assert 'docker push "${IMAGE_TAG}"' in container_job
    assert 'docker pull "${IMAGE}@${digest}"' in container_job
    assert "image: ${{ steps.publish.outputs.reference }}" in container_job
    assert "create_container_evidence.py" in container_job
    assert "--platform linux/amd64" in container_job
    assert "RELEASE_EVIDENCE_RECIPIENT_PUBLIC_KEY" in container_job
    assert "upload-artifact: false" in container_job

    assert "needs: [release-build, release-container]" in assemble_job
    assert 'python-version: "3.12"' in assemble_job
    assert "packages: write" not in assemble_job
    assert "contents: write" not in assemble_job
    assert "attestations: write" not in assemble_job
    assert "render-release.py" in assemble_job
    assert "assemble_release_evidence.py" in assemble_job
    assert "smart-factory-monitor-source-evidence" in assemble_job
    assert "smart-factory-monitor-container-evidence" in assemble_job
    assert "smart-factory-monitor-release-evidence" in assemble_job
    assert "Verify complete release bundle offline" in assemble_job
    assert "python -m smart_factory.release_verification dist" in assemble_job
    assert "--expected-version" in assemble_job
    assert "--expected-revision" in assemble_job
    assert "--expected-image-reference" in assemble_job
    assert "PRIVATE_KEY" not in assemble_job


def test_attestation_and_draft_creation_use_isolated_permissions() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    attest_job = workflow.split("  release-attest:", maxsplit=1)[1].split(
        "\n  release-draft:", maxsplit=1
    )[0]
    draft_job = workflow.split("  release-draft:", maxsplit=1)[1].split("\n  compose:", maxsplit=1)[
        0
    ]

    assert "needs: release-assemble" in attest_job
    assert "attestations: write" in attest_job
    assert "id-token: write" in attest_job
    assert "contents: write" not in attest_job
    assert "github.event.repository.visibility == 'public'" in attest_job
    assert "vars.ENABLE_GITHUB_ATTESTATIONS == 'true'" in attest_job
    assert "subject-checksums: dist/SHA256SUMS" in attest_job
    assert "subject-name: ${{ needs.release-assemble.outputs.image }}" in attest_job
    assert "subject-digest: ${{ needs.release-assemble.outputs.digest }}" in attest_job
    assert "python -m build" not in attest_job
    assert "anchore/sbom-action" not in attest_job

    assert "needs: [release-assemble, release-attest]" in draft_job
    assert "needs.release-assemble.result == 'success'" in draft_job
    assert "needs.release-attest.result == 'success'" in draft_job
    assert "needs.release-attest.result == 'skipped'" in draft_job
    assert "contents: write" in draft_job
    assert "id-token: write" not in draft_job
    assert "attestations: write" not in draft_job
    assert 'gh release create "${GITHUB_REF_NAME}"' in draft_job
    assert "--draft" in draft_job
    assert "needs.release-assemble.outputs.image" in draft_job
    assert "needs.release-assemble.outputs.digest" in draft_job
    assert "needs.release-assemble.outputs.release_revision" in draft_job
    assert "needs.release-assemble.outputs.release_version" in draft_job
    assert "${GITHUB_SHA}" not in draft_job
    assert "gh release edit" not in draft_job
    assert "sha256sum --check SHA256SUMS" in draft_job
    assert "Publish only after" in draft_job
    assert "retention-days: 30" not in draft_job
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
        "release-signing-private.pem",
        "release-signing-public.pem",
        "*.release-signature.json",
        "recovered*.spdx.json",
    ):
        assert ignored_name in gitignore
        assert ignored_name in dockerignore


def test_package_exposes_offline_release_verifier() -> None:
    project = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'smart-factory-verify-release = "smart_factory.release_verification:main"' in project
    assert 'smart-factory-release-signature = "smart_factory.release_signature:main"' in project


def test_ci_never_receives_external_release_signing_authority() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "RELEASE_SIGNING_PRIVATE_KEY" not in workflow
    assert "RELEASE_SIGNING_KEY_PASSWORD" not in workflow
    assert "smart-factory-release-signature sign" not in workflow


def test_colocated_audit_root_is_explicitly_limited_to_local_development() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    environment_example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    keyring = (REPOSITORY_ROOT / "src/smart_factory/infrastructure/audit/keyring.py").read_text(
        encoding="utf-8"
    )

    assert compose.count('AUDIT_ATTESTATION_ALLOW_COLOCATED_ROOT: "true"') == 3
    assert "AUDIT_ATTESTATION_ALLOW_COLOCATED_ROOT=false" in environment_example
    assert "AUDIT_ATTESTATION_TRUSTED_ROOT_KEY_ID=" in environment_example
    assert "trusted_root_key_id_path" not in keyring
