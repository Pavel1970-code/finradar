import json
import re
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from finradar.application.analytical_service import AnalyticalResult
from finradar.application.forecast_history import (
    ForecastHistoryDetails,
    ForecastHistoryItem,
    HistoricalFiscalConsequence,
    HistoricalFiscalObligation,
)
from finradar.domain.financial_snapshot import FinancialEventKind
from finradar.domain.forecast import ForecastEvent, ForecastPoint, ForecastResult
from finradar.infrastructure.models import (
    FiscalAnalysisRun,
    SourceSnapshot,
    SynchronizationRun,
)
from finradar.infrastructure.snapshot_codec import decode_snapshot


ALGORITHM_VERSION = "fiscal-v2"
SCHEMA_VERSION = 1
DEMO_CURSOR_PATTERN = re.compile(r"^demo:(?P<id>[a-z][a-z0-9_]{0,63}):v(?P<version>\d+)$")


class SqlAlchemyFiscalAnalysisHistory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        result: AnalyticalResult,
        *,
        analysis_date: date,
        horizon_days: int,
        synchronization_run_id: str | None,
    ) -> str:
        content_json = encode_analysis_result(
            result,
            analysis_date=analysis_date,
            horizon_days=horizon_days,
            synchronization_run_id=synchronization_run_id,
        )
        stored = FiscalAnalysisRun(
            synchronization_run_id=synchronization_run_id,
            analysis_date=analysis_date,
            horizon_days=horizon_days,
            algorithm_version=ALGORITHM_VERSION,
            rule_result_count=len(result.rule_analyses),
            consequence_count=len(result.consequences),
            content_json=content_json,
            content_hash=sha256(content_json.encode("utf-8")).hexdigest(),
        )
        with self._session_factory() as session:
            session.add(stored)
            session.commit()
            return stored.id

    def load_json(self, analysis_run_id: str) -> str:
        with self._session_factory() as session:
            stored = session.scalar(
                select(FiscalAnalysisRun).where(FiscalAnalysisRun.id == analysis_run_id)
            )
            if stored is None:
                raise LookupError("Fiscal analysis run was not found.")
            actual = sha256(stored.content_json.encode("utf-8")).hexdigest()
            if actual != stored.content_hash:
                raise ValueError("Fiscal analysis integrity check failed.")
            return stored.content_json

    def list_recent(self, *, limit: int = 20) -> tuple[ForecastHistoryItem, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("History list limit must be between 1 and 100.")
        with self._session_factory() as session:
            rows = session.execute(
                select(FiscalAnalysisRun, SynchronizationRun, SourceSnapshot)
                .outerjoin(
                    SynchronizationRun,
                    SynchronizationRun.id == FiscalAnalysisRun.synchronization_run_id,
                )
                .outerjoin(
                    SourceSnapshot,
                    SourceSnapshot.synchronization_run_id == SynchronizationRun.id,
                )
                .order_by(FiscalAnalysisRun.created_at.desc())
                .limit(limit)
            ).all()

        items: list[ForecastHistoryItem] = []
        for analysis_run, synchronization_run, source_snapshot in rows:
            try:
                details = _decode_history_row(
                    analysis_run,
                    synchronization_run,
                    source_snapshot,
                )
                items.append(details.item)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                items.append(
                    ForecastHistoryItem(
                        analysis_run_id=analysis_run.id,
                        created_at=analysis_run.created_at,
                        analysis_date=analysis_run.analysis_date,
                        horizon_days=analysis_run.horizon_days,
                        company_name="Сохранённый прогноз",
                        currency="",
                        readiness_status=(
                            synchronization_run.readiness_status
                            if synchronization_run is not None
                            else "unknown"
                        ),
                        scenario_id=None,
                        scenario_version=None,
                        first_gap_date=None,
                        minimum_balance=None,
                        required_funding=None,
                        available=False,
                        error_message=(
                            "Запись недоступна: проверка целостности не пройдена."
                        ),
                    )
                )
        return tuple(items)

    def load_details(self, analysis_run_id: str) -> ForecastHistoryDetails:
        with self._session_factory() as session:
            row = session.execute(
                select(FiscalAnalysisRun, SynchronizationRun, SourceSnapshot)
                .outerjoin(
                    SynchronizationRun,
                    SynchronizationRun.id == FiscalAnalysisRun.synchronization_run_id,
                )
                .outerjoin(
                    SourceSnapshot,
                    SourceSnapshot.synchronization_run_id == SynchronizationRun.id,
                )
                .where(FiscalAnalysisRun.id == analysis_run_id)
            ).one_or_none()
        if row is None:
            raise LookupError("Fiscal analysis run was not found.")
        return _decode_history_row(*row)


def encode_analysis_result(
    result: AnalyticalResult,
    *,
    analysis_date: date,
    horizon_days: int,
    synchronization_run_id: str | None,
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "analysis_date": analysis_date.isoformat(),
        "horizon_days": horizon_days,
        "synchronization_run_id": synchronization_run_id,
        "result": _json_value(result),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__type__": type(value).__name__,
            **{
                item.name: _json_value(getattr(value, item.name))
                for item in fields(value)
            },
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_value(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _decode_history_row(
    analysis_run: FiscalAnalysisRun,
    synchronization_run: SynchronizationRun | None,
    source_snapshot: SourceSnapshot | None,
) -> ForecastHistoryDetails:
    if synchronization_run is None or source_snapshot is None:
        raise ValueError("Analysis history has no linked financial snapshot.")
    actual_analysis_hash = sha256(
        analysis_run.content_json.encode("utf-8")
    ).hexdigest()
    if actual_analysis_hash != analysis_run.content_hash:
        raise ValueError("Fiscal analysis integrity check failed.")
    actual_snapshot_hash = sha256(
        source_snapshot.content_json.encode("utf-8")
    ).hexdigest()
    if actual_snapshot_hash != source_snapshot.content_hash:
        raise ValueError("Synchronization snapshot integrity check failed.")

    snapshot = decode_snapshot(source_snapshot.content_json)
    payload = json.loads(analysis_run.content_json)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported fiscal analysis history schema version.")
    if payload.get("analysis_date") != analysis_run.analysis_date.isoformat():
        raise ValueError("Fiscal analysis date does not match its audit metadata.")
    if payload.get("horizon_days") != analysis_run.horizon_days:
        raise ValueError("Fiscal analysis horizon does not match its audit metadata.")
    result = _typed_mapping(payload.get("result"), "AnalyticalResult")
    forecast = _decode_forecast(result.get("forecast"))
    stress_forecast = _decode_forecast(result.get("stress_forecast"))
    if forecast.start_date != analysis_run.analysis_date:
        raise ValueError("Stored forecast start date does not match the analysis date.")

    company_name = snapshot.company.name if snapshot.company is not None else "Компания"
    currency = snapshot.company.base_currency if snapshot.company is not None else ""
    scenario_id, scenario_version = _scenario_reference(snapshot.source_cursor)
    item = ForecastHistoryItem(
        analysis_run_id=analysis_run.id,
        created_at=analysis_run.created_at,
        analysis_date=analysis_run.analysis_date,
        horizon_days=analysis_run.horizon_days,
        company_name=company_name,
        currency=currency,
        readiness_status=synchronization_run.readiness_status,
        scenario_id=scenario_id,
        scenario_version=scenario_version,
        first_gap_date=forecast.first_gap_date,
        minimum_balance=forecast.minimum_balance,
        required_funding=forecast.required_funding,
        available=True,
    )
    return ForecastHistoryDetails(
        item=item,
        forecast=forecast,
        stress_forecast=stress_forecast,
        forecast_events=tuple(
            _decode_forecast_event(value)
            for value in _typed_sequence(result.get("forecast_events"))
        ),
        stress_forecast_events=tuple(
            _decode_forecast_event(value)
            for value in _typed_sequence(result.get("stress_forecast_events"))
        ),
        payment_events=tuple(
            event
            for event in snapshot.events
            if event.kind is FinancialEventKind.PLANNED
        ),
        obligations=_decode_obligations(result.get("rule_analyses")),
        consequences=tuple(
            _decode_consequence(value)
            for value in _typed_sequence(result.get("consequences"))
        ),
    )


def _decode_forecast(value: object) -> ForecastResult:
    payload = _typed_mapping(value, "ForecastResult")
    points = tuple(
        ForecastPoint(
            day=date.fromisoformat(point["day"]),
            inflow=Decimal(point["inflow"]),
            outflow=Decimal(point["outflow"]),
            closing_balance=Decimal(point["closing_balance"]),
        )
        for item in _typed_sequence(payload.get("points"))
        for point in (_typed_mapping(item, "ForecastPoint"),)
    )
    return ForecastResult(
        start_date=date.fromisoformat(payload["start_date"]),
        end_date=date.fromisoformat(payload["end_date"]),
        opening_balance=Decimal(payload["opening_balance"]),
        closing_balance=Decimal(payload["closing_balance"]),
        minimum_balance=Decimal(payload["minimum_balance"]),
        first_gap_date=(
            date.fromisoformat(payload["first_gap_date"])
            if payload.get("first_gap_date") is not None
            else None
        ),
        required_funding=Decimal(payload["required_funding"]),
        points=points,
    )


def _decode_forecast_event(value: object) -> ForecastEvent:
    payload = _typed_mapping(value, "ForecastEvent")
    return ForecastEvent(
        due_date=date.fromisoformat(payload["due_date"]),
        amount=Decimal(payload["amount"]),
        is_inflow=_strict_bool(payload["is_inflow"]),
        reference=payload.get("reference", ""),
    )


def _decode_obligations(value: object) -> tuple[HistoricalFiscalObligation, ...]:
    obligations: list[HistoricalFiscalObligation] = []
    for raw_analysis in _typed_sequence(value):
        analysis = _typed_mapping(raw_analysis, "RuleAnalysis")
        calculation = _typed_mapping(
            analysis.get("calculation"), "FiscalCalculationResult"
        )
        obligation_value = calculation.get("obligation")
        if obligation_value is None:
            continue
        obligation = _typed_mapping(obligation_value, "FiscalObligation")
        reconciliation_value = analysis.get("reconciliation")
        outstanding = Decimal(obligation["amount"])
        if reconciliation_value is not None:
            reconciliation = _typed_mapping(
                reconciliation_value, "ReconciliationResult"
            )
            outstanding = Decimal(reconciliation["outstanding_amount"])
        obligations.append(
            HistoricalFiscalObligation(
                title=obligation["title"],
                amount=Decimal(obligation["amount"]),
                outstanding_amount=outstanding,
                currency=obligation["currency"],
                due_date=date.fromisoformat(obligation["due_date"]),
                recipient_name=_stored_counterparty_name(
                    obligation.get("payment_recipient")
                ),
                period_start=_optional_stored_date(obligation.get("period_start")),
                period_end=_optional_stored_date(obligation.get("period_end")),
            )
        )
    return tuple(obligations)


def _decode_consequence(value: object) -> HistoricalFiscalConsequence:
    payload = _typed_mapping(value, "FiscalConsequence")
    amount = payload.get("amount")
    return HistoricalFiscalConsequence(
        consequence_type=payload["consequence_type"],
        status=payload["status"],
        amount=Decimal(amount) if amount is not None else None,
        currency=payload["currency"],
        assessment_date=date.fromisoformat(payload["assessment_date"]),
    )


def _scenario_reference(cursor: str | None) -> tuple[str | None, int | None]:
    if cursor is None or (match := DEMO_CURSOR_PATTERN.fullmatch(cursor)) is None:
        return None, None
    return match.group("id"), int(match.group("version"))


def _typed_mapping(value: object, expected_type: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("__type__") != expected_type:
        raise ValueError(f"Expected stored {expected_type} value.")
    return value


def _typed_sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a stored sequence value.")
    return value


def _strict_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Expected a stored boolean value.")
    return value


def _stored_counterparty_name(value: object) -> str:
    if value is None:
        return "Налоговый орган"
    payload = _typed_mapping(value, "CounterpartyReference")
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Stored counterparty name is invalid.")
    return name


def _optional_stored_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Stored date value is invalid.")
    return date.fromisoformat(value)
