from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from finradar.domain.data_readiness import ReadinessReport
from finradar.domain.financial_snapshot import FinancialSnapshot
from finradar.infrastructure.models import SourceSnapshot, SynchronizationRun
from finradar.infrastructure.snapshot_codec import decode_snapshot, encode_snapshot


class SqlAlchemySynchronizationHistory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        snapshot: FinancialSnapshot,
        readiness: ReadinessReport,
    ) -> str:
        content_json = encode_snapshot(snapshot)
        content_hash = sha256(content_json.encode("utf-8")).hexdigest()
        run = SynchronizationRun(
            source_system=snapshot.source_system,
            captured_at=snapshot.captured_at,
            readiness_status=readiness.status.value,
            issue_count=len(readiness.issues),
        )
        run.snapshot = SourceSnapshot(
            content_json=content_json,
            content_hash=content_hash,
        )

        with self._session_factory() as session:
            session.add(run)
            session.commit()
            return run.id

    def load_snapshot(self, synchronization_run_id: str) -> FinancialSnapshot:
        with self._session_factory() as session:
            stored = session.scalar(
                select(SourceSnapshot).where(
                    SourceSnapshot.synchronization_run_id == synchronization_run_id
                )
            )
            if stored is None:
                raise LookupError("Synchronization snapshot was not found.")

            actual_hash = sha256(stored.content_json.encode("utf-8")).hexdigest()
            if actual_hash != stored.content_hash:
                raise ValueError("Synchronization snapshot integrity check failed.")
            return decode_snapshot(stored.content_json)

