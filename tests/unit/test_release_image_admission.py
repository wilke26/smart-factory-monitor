from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = (
    REPOSITORY_ROOT / "deploy" / "kubernetes" / "policies" / "release-image-admission.yaml"
)
AZURE_NAMESPACE_PATH = (
    REPOSITORY_ROOT / "deploy" / "kubernetes" / "overlays" / "azure" / "namespace.yaml"
)
IMAGE_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?(?::[0-9]+)?"
    r"(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)+@sha256:[0-9a-f]{64}$"
)


def test_admission_policy_is_fail_closed_and_scoped() -> None:
    policy = POLICY_PATH.read_text(encoding="utf-8")

    assert policy.count("apiVersion: admissionregistration.k8s.io/v1") == 2
    assert "kind: ValidatingAdmissionPolicy\n" in policy
    assert "kind: ValidatingAdmissionPolicyBinding\n" in policy
    assert "failurePolicy: Fail" in policy
    assert 'operations: ["CREATE", "UPDATE"]' in policy
    assert 'resources: ["deployments"]' in policy
    assert "objectSelector:" not in policy
    assert "validationActions: [Deny, Audit]" in policy
    assert 'security.smart-factory-monitor.io/require-digest-images: "true"' in policy
    assert "initContainers" in policy


def test_digest_pattern_rejects_tags_and_accepts_release_references() -> None:
    digest = "sha256:" + "a" * 64

    assert IMAGE_PATTERN.fullmatch(f"ghcr.io/wilke26/smart-factory-monitor@{digest}")
    assert IMAGE_PATTERN.fullmatch(f"registry.example:5000/team/application@{digest}")
    assert not IMAGE_PATTERN.fullmatch("smart-factory-monitor:0.22.0")
    assert not IMAGE_PATTERN.fullmatch(f"smart-factory-monitor@{digest}")
    assert not IMAGE_PATTERN.fullmatch(f"ghcr.io/wilke26/smart-factory-monitor:0.22.0@{digest}")
    assert not IMAGE_PATTERN.fullmatch("ghcr.io/wilke26/smart-factory-monitor@sha256:not-a-digest")
    assert not IMAGE_PATTERN.fullmatch(f"GHCR.io/wilke26/smart-factory-monitor@{digest}")


def test_azure_namespace_explicitly_enables_release_image_policy() -> None:
    namespace = AZURE_NAMESPACE_PATH.read_text(encoding="utf-8")

    assert 'security.smart-factory-monitor.io/require-digest-images: "true"' in namespace


def test_admission_policy_kustomization_renders() -> None:
    result = subprocess.run(
        ["kubectl", "kustomize", "deploy/kubernetes/policies"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "kind: ValidatingAdmissionPolicy\n" in result.stdout
    assert "kind: ValidatingAdmissionPolicyBinding\n" in result.stdout


def test_ci_renders_standalone_admission_policy() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "kubectl kustomize deploy/kubernetes/policies" in workflow
