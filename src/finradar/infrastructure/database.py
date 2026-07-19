import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from platformdirs import user_data_path
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CORE_DATA_DIRECTORY_ENV = "FINRADAR_CORE_DATA_DIR"
IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = (
    Path(getattr(sys, "_MEIPASS")).resolve()
    if IS_FROZEN
    else PROJECT_ROOT
)
_configured_data_directory = os.environ.get(CORE_DATA_DIRECTORY_ENV)
DATA_DIRECTORY = (
    Path(_configured_data_directory).expanduser().resolve()
    if _configured_data_directory
    else (
        user_data_path("FinRadar", "FinRadar", roaming=False)
        if IS_FROZEN
        else PROJECT_ROOT / "data"
    )
)
DATABASE_PATH = DATA_DIRECTORY / "finradar.db"
REGULATORY_ARCHIVE_DIRECTORY = DATA_DIRECTORY / "regulatory-archive"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
ALEMBIC_CONFIG_PATH = RESOURCE_ROOT / "alembic.ini"
MIGRATIONS_DIRECTORY = RESOURCE_ROOT / "migrations"
INITIAL_REVISION = "0001_initial"
CORE_TABLES = {"companies", "cash_accounts", "cash_flow_items"}


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    del connection_record

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def initialize_database() -> None:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    migrate_database(engine)


def migrate_database(target_engine: Engine) -> None:
    configuration = Config(str(ALEMBIC_CONFIG_PATH))
    configuration.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))

    with target_engine.begin() as connection:
        configuration.attributes["connection"] = connection
        table_names = set(inspect(connection).get_table_names())

        if "alembic_version" not in table_names:
            existing_core_tables = table_names & CORE_TABLES
            if existing_core_tables and existing_core_tables != CORE_TABLES:
                missing = ", ".join(sorted(CORE_TABLES - existing_core_tables))
                raise RuntimeError(
                    "Cannot baseline a partial prototype database. "
                    f"Missing tables: {missing}."
                )
            if existing_core_tables == CORE_TABLES:
                command.stamp(configuration, INITIAL_REVISION)

        command.upgrade(configuration, "head")
