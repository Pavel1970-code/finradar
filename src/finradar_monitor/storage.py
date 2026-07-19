"""SQLite storage containing public regulatory material only."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class PublicDocument:
    source_url: str
    document_id: str
    title: str
    publisher: str
    language: str
    content: str
    fetched_at: datetime
    publication_date: date | None = None
    effective_date: date | None = None
    source_id: str | None = None


class RegulatoryStorage:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path.resolve()

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS public_documents (
                    source_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    publisher TEXT NOT NULL,
                    publication_date TEXT,
                    effective_date TEXT,
                    language TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    UNIQUE (source_url, document_id, content_sha256)
                )
                """
            )

    def record_document(self, document: PublicDocument) -> str:
        source_id = document.source_id or str(uuid4())
        content_sha256 = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO public_documents (
                    source_id,
                    source_url,
                    document_id,
                    title,
                    publisher,
                    publication_date,
                    effective_date,
                    language,
                    content,
                    content_sha256,
                    fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    document.source_url,
                    document.document_id,
                    document.title,
                    document.publisher,
                    document.publication_date.isoformat()
                    if document.publication_date
                    else None,
                    document.effective_date.isoformat()
                    if document.effective_date
                    else None,
                    document.language,
                    document.content,
                    content_sha256,
                    document.fetched_at.isoformat(),
                ),
            )
        return source_id

    def count_documents(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM public_documents").fetchone()
        return int(row[0]) if row else 0

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
