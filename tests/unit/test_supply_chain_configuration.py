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


def test_container_installation_enforces_hash_locks() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("--require-hashes") == 2
    assert "requirements/build.lock" in dockerfile
    assert "requirements/runtime.lock" in dockerfile
    assert "pip install --upgrade" not in dockerfile
