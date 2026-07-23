"""Async SQLite storage for CTIE."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from ctie.config import Settings
from ctie.models.app import AppInput, Document, SearchResult
from ctie.models.result import AppResearchResult

logger = structlog.get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_apps INTEGER NOT NULL DEFAULT 0,
    completed_apps INTEGER NOT NULL DEFAULT 0,
    failed_apps INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS apps (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    website TEXT NOT NULL,
    category_hint TEXT NOT NULL,
    hints_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    updated_at TEXT NOT NULL,
    error TEXT,
    result_json TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    cleaned_text TEXT NOT NULL,
    fetch_method TEXT NOT NULL,
    status_code INTEGER,
    fetched_at TEXT NOT NULL,
    content_length INTEGER NOT NULL,
    search_result_json TEXT,
    UNIQUE(app_id, url),
    FOREIGN KEY (app_id) REFERENCES apps(id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT PRIMARY KEY,
    graph_state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class StoredApp:
    """App row with runtime state."""

    id: int
    run_id: str
    name: str
    website: str
    category_hint: str
    hints: list[str]
    status: str
    updated_at: str
    error: str | None
    result: AppResearchResult | None


class SQLiteStore:
    """Async SQLite-backed store for pipeline state and artifacts."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def _connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        conn = await aiosqlite.connect(self.db_path, timeout=30.0)
        try:
            conn.row_factory = aiosqlite.Row
            yield conn
        finally:
            await conn.close()

    async def initialize(self) -> None:
        """Create schema if it does not exist and optimize SQLite settings.
        
        Enables WAL mode for better concurrency and sets optimal pragmas
        for production use.
        """
        async with self._connect() as conn:
            # Enable WAL mode for better concurrency (allows concurrent reads during writes)
            await conn.execute("PRAGMA journal_mode=WAL")
            
            # Optimize performance pragmas
            await conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes, still safe with WAL
            await conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            await conn.execute("PRAGMA temp_store=MEMORY")  # Store temp tables in memory
            await conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
            
            # Create schema
            await conn.executescript(SCHEMA)
            await conn.commit()
        logger.info("sqlite_store_initialized", db_path=str(self.db_path), wal_enabled=True)

    async def create_run(self, run_id: str, total_apps: int) -> None:
        now = _now_iso()
        async with self._lock, self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO runs (run_id, started_at, total_apps, completed_apps, failed_apps)
                VALUES (?, ?, ?, 0, 0)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (run_id, now, total_apps),
            )
            await conn.commit()

    async def upsert_app(self, app: AppInput, run_id: str, status: str = "pending") -> None:
        now = _now_iso()
        async with self._lock, self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO apps (id, run_id, name, website, category_hint, hints_json, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    run_id=excluded.run_id,
                    name=excluded.name,
                    website=excluded.website,
                    category_hint=excluded.category_hint,
                    hints_json=excluded.hints_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    app.id,
                    run_id,
                    app.name,
                    str(app.website),
                    app.category_hint,
                    json.dumps(app.hints),
                    status,
                    now,
                ),
            )
            await conn.commit()

    async def update_app_status(
        self,
        app_id: int,
        status: str,
        error: str | None = None,
        result: AppResearchResult | None = None,
    ) -> None:
        now = _now_iso()
        result_json = result.model_dump_json() if result else None
        async with self._lock, self._connect() as conn:
            await conn.execute(
                """
                UPDATE apps SET status = ?, error = ?, result_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error, result_json, now, app_id),
            )
            await conn.commit()

    async def get_app(self, app_id: int) -> StoredApp | None:
        async with self._lock, self._connect() as conn:
            row = await conn.execute_fetchall(
                "SELECT * FROM apps WHERE id = ? LIMIT 1", (app_id,)
            )
            if not row:
                return None
            return self._row_to_app(row[0])

    async def list_apps(
        self, run_id: str | None = None, status: str | None = None
    ) -> list[StoredApp]:
        query = "SELECT * FROM apps"
        params: list[Any] = []
        conditions: list[str] = []
        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id"
        async with self._lock, self._connect() as conn:
            rows = await conn.execute_fetchall(query, params)
            return [self._row_to_app(r) for r in rows]

    async def get_pending_app_ids(self, run_id: str) -> list[int]:
        async with self._lock, self._connect() as conn:
            rows = await conn.execute_fetchall(
                "SELECT id FROM apps WHERE run_id = ? AND status IN ('pending', 'failed') ORDER BY id",
                (run_id,),
            )
            return [r["id"] for r in rows]

    async def upsert_document(self, app_id: int, document: Document, search_result: SearchResult | None = None) -> None:
        now = _now_iso()
        async with self._lock, self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO documents
                    (app_id, url, title, cleaned_text, fetch_method, status_code, fetched_at, content_length, search_result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(app_id, url) DO UPDATE SET
                    app_id=excluded.app_id,
                    title=excluded.title,
                    cleaned_text=excluded.cleaned_text,
                    fetch_method=excluded.fetch_method,
                    status_code=excluded.status_code,
                    fetched_at=excluded.fetched_at,
                    content_length=excluded.content_length,
                    search_result_json=excluded.search_result_json
                """,
                (
                    app_id,
                    str(document.url),
                    document.title,
                    document.cleaned_text,
                    document.fetch_method,
                    document.status_code,
                    document.fetched_at or now,
                    document.content_length,
                    search_result.model_dump_json() if search_result else None,
                ),
            )
            await conn.commit()

    async def get_document(self, url: str, app_id: int | None = None) -> Document | None:
        query = "SELECT * FROM documents WHERE url = ?"
        params: list[Any] = [url]
        if app_id is not None:
            query += " AND app_id = ?"
            params.append(app_id)
        query += " LIMIT 1"
        async with self._lock, self._connect() as conn:
            rows = await conn.execute_fetchall(query, params)
            if not rows:
                return None
            row = rows[0]
            return Document(
                url=row["url"],
                cleaned_text=row["cleaned_text"],
                title=row["title"],
                fetch_method=row["fetch_method"],
                status_code=row["status_code"],
                fetched_at=row["fetched_at"],
                content_length=row["content_length"],
            )

    async def get_documents_for_app(self, app_id: int) -> list[Document]:
        async with self._lock, self._connect() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM documents WHERE app_id = ? ORDER BY fetched_at",
                (app_id,),
            )
            return [
                Document(
                    url=r["url"],
                    cleaned_text=r["cleaned_text"],
                    title=r["title"],
                    fetch_method=r["fetch_method"],
                    status_code=r["status_code"],
                    fetched_at=r["fetched_at"],
                    content_length=r["content_length"],
                )
                for r in rows
            ]

    async def update_run_summary(
        self,
        run_id: str,
        completed_apps: int,
        failed_apps: int,
        summary_json: str,
    ) -> None:
        now = _now_iso()
        async with self._lock, self._connect() as conn:
            await conn.execute(
                """
                UPDATE runs
                SET completed_apps = ?, failed_apps = ?, summary_json = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (completed_apps, failed_apps, summary_json, now, run_id),
            )
            await conn.commit()

    async def save_checkpoint(self, run_id: str, graph_state: dict[str, Any]) -> None:
        now = _now_iso()
        async with self._lock, self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO checkpoints (run_id, graph_state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    graph_state_json=excluded.graph_state_json,
                    updated_at=excluded.updated_at
                """,
                (run_id, json.dumps(graph_state), now),
            )
            await conn.commit()

    async def get_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        async with self._lock, self._connect() as conn:
            rows = await conn.execute_fetchall(
                "SELECT graph_state_json FROM checkpoints WHERE run_id = ? LIMIT 1", (run_id,)
            )
            if not rows:
                return None
            return json.loads(rows[0]["graph_state_json"])

    async def export_to(self, target_path: Path) -> None:
        """Backup the SQLite database to ``target_path``."""
        target_path = target_path.expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock, self._connect() as conn:
            await conn.execute("VACUUM INTO ?", (str(target_path),))
            await conn.commit()
        logger.info("sqlite_store_exported", target=str(target_path))

    async def import_from(self, source_path: Path) -> None:
        """Replace the current database with ``source_path``."""
        source_path = source_path.expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Database backup not found: {source_path}")
        import shutil

        shutil.copy2(source_path, self.db_path)
        logger.info("sqlite_store_imported", source=str(source_path), target=str(self.db_path))

    def _row_to_app(self, row: aiosqlite.Row) -> StoredApp:
        result_json = row["result_json"]
        result = None
        if result_json:
            try:
                result = AppResearchResult.model_validate_json(result_json)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stored_app_result_parse_failed",
                    app_id=row["id"],
                    error=str(exc),
                )
        return StoredApp(
            id=row["id"],
            run_id=row["run_id"],
            name=row["name"],
            website=row["website"],
            category_hint=row["category_hint"],
            hints=json.loads(row["hints_json"] or "[]"),
            status=row["status"],
            updated_at=row["updated_at"],
            error=row["error"],
            result=result,
        )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_store(settings: Settings | None = None) -> SQLiteStore:
    from ctie.config import get_settings

    settings = settings or get_settings()
    return SQLiteStore(settings.ctie_db_path)
