import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from finradar.application.analytical_service import AnalyticalResult
from finradar.infrastructure.models import FiscalAnalysisRun


ALGORITHM_VERSION = "fiscal-v1"
SCHEMA_VERSION = 1


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

