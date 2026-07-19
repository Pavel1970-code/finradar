import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from finradar.application.accounting_connector import SynchronizationRequest
from finradar.application.analytical_service import analyze_financial_risk
from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.infrastructure.connectors.demo import DemoAccountingConnector
from finradar.infrastructure.database import migrate_database
from finradar.infrastructure.fiscal_analysis_history import (
    ALGORITHM_VERSION,
    SqlAlchemyFiscalAnalysisHistory,
)
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)


AS_OF = date(2026, 7, 19)


def test_analysis_history_is_hashed_and_immutable(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'analysis.db'}")
    migrate_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    history = SqlAlchemyFiscalAnalysisHistory(session_factory)
    snapshot = DemoAccountingConnector(as_of=AS_OF).synchronize(
        SynchronizationRequest()
    )
    result = analyze_financial_risk(snapshot, (), as_of=AS_OF, horizon_days=30)

    run_id = history.record(
        result,
        analysis_date=AS_OF,
        horizon_days=30,
        synchronization_run_id=None,
    )
    payload = json.loads(history.load_json(run_id))

    assert payload["algorithm_version"] == ALGORITHM_VERSION
    assert payload["analysis_date"] == "2026-07-19"
    assert payload["result"]["__type__"] == "AnalyticalResult"

    with pytest.raises(DatabaseError, match="fiscal_analysis_runs is immutable"):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE fiscal_analysis_runs SET content_json = '{}' WHERE id = :id"),
                {"id": run_id},
            )


def test_synchronization_and_analysis_history_are_linked(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'linked.db'}")
    migrate_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    analysis_history = SqlAlchemyFiscalAnalysisHistory(session_factory)

    outcome = synchronize_and_forecast(
        DemoAccountingConnector(as_of=AS_OF),
        as_of=AS_OF,
        recorder=SqlAlchemySynchronizationHistory(session_factory),
        analysis_recorder=analysis_history,
    )

    assert outcome.synchronization_run_id is not None
    assert outcome.fiscal_analysis_run_id is not None
    payload = json.loads(analysis_history.load_json(outcome.fiscal_analysis_run_id))
    assert payload["synchronization_run_id"] == outcome.synchronization_run_id
