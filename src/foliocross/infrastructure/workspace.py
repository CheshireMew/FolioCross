"""Workspace layout and SQLite migration management."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Iterator


class Workspace:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self.db_path = self.root / "foliocross.db"
        self.library_dir = self.root / "library"
        self.jobs_dir = self.root / "jobs"
        self.exports_dir = self.root / "exports"
        self.logs_dir = self.root / "logs"
        self.imports_dir = self.root / "imports"

    @classmethod
    def default(cls) -> "Workspace":
        configured = os.environ.get("FOLIOCROSS_WORKSPACE", "").strip()
        if configured:
            return cls(configured)
        return cls(Path.cwd() / "workspace")

    def initialize(self) -> None:
        for directory in (
            self.root,
            self.library_dir,
            self.jobs_dir,
            self.exports_dir,
            self.logs_dir,
            self.imports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        with self.session() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations")
            }
            migration_root = files("foliocross.infrastructure.migrations")
            for resource in sorted(migration_root.iterdir(), key=lambda item: item.name):
                if not resource.name.endswith(".sql"):
                    continue
                version = int(resource.name.split("_", 1)[0])
                if version in applied:
                    continue
                connection.executescript(resource.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (version,),
                )
            connection.commit()

    def connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def book_source_dir(self, book_id: str) -> Path:
        return self.library_dir / book_id / "source"

    def job_artifact_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "artifacts"

    def book_export_dir(self, book_id: str) -> Path:
        return self.exports_dir / book_id
