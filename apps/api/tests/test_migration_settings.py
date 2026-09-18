from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.db.migration_settings import MigrationSettings
from app.settings import Settings

API_ROOT = Path(__file__).parents[1]


def test_migration_settings_require_only_a_valid_postgresql_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://visualops:secret@127.0.0.1:5432/visualops",
    )

    migration_settings = MigrationSettings()

    assert migration_settings.database_url == (
        "postgresql+asyncpg://visualops:secret@127.0.0.1:5432/visualops"
    )
    with pytest.raises(ValidationError):
        Settings()


def test_alembic_offline_sql_requires_only_database_url() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=API_ROOT,
        env={
            "DATABASE_URL": (
                "postgresql+asyncpg://visualops:secret@127.0.0.1:5432/visualops"
            )
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE organizations" in result.stdout
    assert "INSERT INTO alembic_version" in result.stdout


@pytest.mark.parametrize(
    "database_url",
    [
        "not-a-url",
        "sqlite+aiosqlite:///tmp/visualops.db",
        "postgresql://visualops:secret@127.0.0.1:5432/visualops",
    ],
)
def test_migration_settings_reject_invalid_or_non_postgresql_urls(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)

    with pytest.raises(ValidationError):
        MigrationSettings()
