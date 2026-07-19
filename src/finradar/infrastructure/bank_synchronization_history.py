from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from finradar.domain.banking import BankSynchronizationBatch
from finradar.infrastructure.bank_snapshot_codec import (
    decode_bank_batch,
    encode_bank_batch,
)
from finradar.infrastructure.models import (
    BankStatementSnapshot,
    BankSynchronizationRun,
)


class SqlAlchemyBankSynchronizationHistory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(self, batch: BankSynchronizationBatch) -> str:
        content_json = encode_bank_batch(batch)
        run = BankSynchronizationRun(
            source_system=batch.source_system,
            captured_at=batch.captured_at,
            available=int(batch.available),
            statement_count=len(batch.statements),
            transaction_count=len(batch.transactions),
            issue_count=len(batch.source_issues),
            next_cursor=batch.next_cursor,
        )
        run.snapshot = BankStatementSnapshot(
            content_json=content_json,
            content_hash=sha256(content_json.encode("utf-8")).hexdigest(),
        )
        with self._session_factory() as session:
            session.add(run)
            session.commit()
            return run.id

    def load_batch(self, run_id: str) -> BankSynchronizationBatch:
        with self._session_factory() as session:
            stored = session.scalar(
                select(BankStatementSnapshot).where(
                    BankStatementSnapshot.bank_synchronization_run_id == run_id
                )
            )
            if stored is None:
                raise LookupError("Bank synchronization snapshot was not found.")
            actual_hash = sha256(stored.content_json.encode("utf-8")).hexdigest()
            if actual_hash != stored.content_hash:
                raise ValueError("Bank synchronization snapshot integrity check failed.")
            return decode_bank_batch(stored.content_json)
