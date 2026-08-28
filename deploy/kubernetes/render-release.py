#!/usr/bin/env python3
"""Render the Azure overlay with an immutable application image digest."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?(?::[0-9]+)?"
    r"(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)+$"
)
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
DEPLOYMENT_COUNT = 3


def _validated_reference(image: str, digest: str) -> str:
    if not IMAGE_PATTERN.fullmatch(image):
        raise ValueError("image must be a lowercase registry/repository reference without a tag")
    if not DIGEST_PATTERN.fullmatch(digest):
        raise ValueError("digest must be a lowercase sha256 digest")
    return f"{image}@{digest}"


def _bind_image_digest(kustomization: str, image: str, digest: str) -> str:
    _validated_reference(image, digest)
    if kustomization.count("    newName:") != 1:
        raise ValueError("expected exactly one image newName in the Azure overlay")
    if kustomization.count("    newTag:") != 1:
        raise ValueError("expected exactly one image newTag in the Azure overlay")

    lines: list[str] = []
    for line in kustomization.splitlines():
        if line.startswith("    newName:"):
            lines.append(f"    newName: {image}")
        elif line.startswith("    newTag:"):
            lines.append(f"    digest: {digest}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def render_release(image: str, digest: str) -> str:
    expected_reference = _validated_reference(image, digest)
    deployment_root = Path(__file__).resolve().parent

    with tempfile.TemporaryDirectory(prefix="smart-factory-release-") as directory:
        copied_root = Path(directory) / "kubernetes"
        shutil.copytree(deployment_root, copied_root)
        overlay = copied_root / "overlays" / "azure" / "kustomization.yaml"
        overlay.write_text(
            _bind_image_digest(overlay.read_text(encoding="utf-8"), image, digest),
            encoding="utf-8",
        )
        result = subprocess.run(
            ["kubectl", "kustomize", str(overlay.parent)],
            check=True,
            capture_output=True,
            text=True,
        )

    rendered = result.stdout
    if rendered.count(f"image: {expected_reference}") != DEPLOYMENT_COUNT:
        raise RuntimeError(
            "rendered release does not bind every application deployment to the digest"
        )
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="lowercase registry/repository reference")
    parser.add_argument("--digest", required=True, help="sha256 image digest")
    parser.add_argument("--output", type=Path, help="output file; stdout when omitted")
    arguments = parser.parse_args()
    rendered = render_release(arguments.image, arguments.digest)
    if arguments.output is None:
        print(rendered, end="")
    else:
        arguments.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
