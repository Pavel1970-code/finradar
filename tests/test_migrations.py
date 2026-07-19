from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from finradar.infrastructure.database import ALEMBIC_CONFIG_PATH, migrate_database


EXPECTED_TABLES = {
    "alembic_version",
    "cash_accounts",
    "cash_flow_items",
    "companies",
    "fiscal_analysis_runs",
    "fiscal_rule_lifecycle_events",
    "fiscal_rule_versions",
    "regulatory_accepted_packages",
    "regulatory_package_imports",
    "regulatory_trusted_key_events",
    "regulatory_trusted_keys",
    "source_snapshots",
    "synchronization_runs",
}


def make_engine(database_path: Path):
    return create_engine(f"sqlite:///{database_path}")


def test_new_database_is_created_at_head(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "new.db")

    migrate_database(engine)

    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0005_regulatory_preflight"
        )


def test_existing_prototype_database_is_baselined_without_data_loss(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "prototype.db")
    configuration = Config(str(ALEMBIC_CONFIG_PATH))
    with engine.begin() as connection:
        configuration.attributes["connection"] = connection
        command.upgrade(configuration, "0001_initial")
        connection.execute(
            text(
                "INSERT INTO companies (id, name, base_currency, created_at) "
                "VALUES ('company-1', 'Fictional Company', 'GEL', '2026-07-18')"
            )
        )
        connection.execute(text("DROP TABLE alembic_version"))

    migrate_database(engine)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM companies")) == (
            "Fictional Company"
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0005_regulatory_preflight"
        )
