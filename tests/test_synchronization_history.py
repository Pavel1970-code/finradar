from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.infrastructure.connectors.demo import DemoAccountingConnector
from finradar.infrastructure.database import migrate_database
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)


AS_OF = date(2026, 7, 18)


def test_synchronization_snapshot_round_trip_and_database_immutability(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    migrate_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    history = SqlAlchemySynchronizationHistory(session_factory)

    outcome = synchronize_and_forecast(
        DemoAccountingConnector(as_of=AS_OF),
        as_of=AS_OF,
        recorder=history,
    )

    assert outcome.synchronization_run_id is not None
    restored = history.load_snapshot(outcome.synchronization_run_id)
    assert restored == outcome.snapshot

    with pytest.raises(DatabaseError, match="source snapshots are immutable"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE source_snapshots SET content_json = '{}' "
                    "WHERE synchronization_run_id = :run_id"
                ),
                {"run_id": outcome.synchronization_run_id},
            )

