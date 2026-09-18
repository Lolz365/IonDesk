from pathlib import Path

COMPOSE_PATH = Path(__file__).parents[3] / "infra/compose/compose.staging.yml"


def test_staging_api_waits_for_successful_migration_job() -> None:
    compose = COMPOSE_PATH.read_text()

    assert "  migrate:\n" in compose
    assert '    command: ["alembic", "upgrade", "head"]' in compose
    assert (
        "      migrate:\n        condition: service_completed_successfully" in compose
    )
