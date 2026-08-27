"""Fast safety checks for the containerized recovery entry points."""

import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("script", "environment", "message"),
    [
        (
            "create-backup.sh",
            {"BACKUP_ID": "../escape"},
            "BACKUP_ID must contain only",
        ),
        (
            "restore-backup.sh",
            {"BACKUP_ID": ""},
            "BACKUP_ID is required",
        ),
        (
            "restore-backup.sh",
            {"BACKUP_ID": "safe", "RESTORE_DATABASE_NAME": "bad-name"},
            "RESTORE_DATABASE_NAME must be",
        ),
        (
            "restore-backup.sh",
            {"BACKUP_ID": "safe", "RESTORE_DATABASE_NAME": "smart_factory"},
            "must differ from the active database",
        ),
        (
            "create-backup.sh",
            {"BACKUP_ID": "a" * 65},
            "must not exceed 64 characters",
        ),
    ],
)
def test_recovery_script_rejects_unsafe_input(
    script: str,
    environment: dict[str, str],
    message: str,
) -> None:
    result = subprocess.run(
        ["sh", str(PROJECT_ROOT / "docker" / "recovery" / script)],
        env={**os.environ, **environment},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert message in result.stderr
