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


def test_restore_defers_foreign_keys_until_after_timescale_restore_mode() -> None:
    source = (PROJECT_ROOT / "docker" / "recovery" / "restore-backup.sh").read_text()

    pre_restore = source.index("SELECT timescaledb_pre_restore()")
    main_restore = source.index("--use-list=/tmp/restore-without-fk.list")
    post_restore = source.index("SELECT timescaledb_post_restore();", pre_restore)
    foreign_keys = source.index("--use-list=/tmp/restore-fk-only.list")

    assert pre_restore < main_restore < post_restore < foreign_keys
