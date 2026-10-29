"""Workspace layout and SQLite migration management."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import uuid
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
        self._local = threading.local()

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
        # Serialize startup across GUI, CLI and workers. executescript() would
        # implicitly commit here, separating DDL from its migration receipt.
        with self.transaction(immediate=True) as connection:
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
                statement = ""
                for line in resource.read_text(encoding="utf-8").splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        self._apply_schema_statement(connection, statement.strip(), version)
                        statement = ""
                if statement.strip():
                    raise ValueError(f"Incomplete migration: {resource.name}")
                if version == 6:
                    self._migrate_owned_paths(connection)
                if version == 7:
                    self._preserve_legacy_artifacts(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (version,),
                )

    @staticmethod
    def _apply_schema_statement(connection, statement: str, version: int) -> None:
        # Versions 1–5 were shipped with autocommit. Only reconcile their
        # known DDL, and only if the already-created object has the exact shape.
        if version <= 5:
            create = re.match(r"CREATE (?:UNIQUE )?(TABLE|INDEX) (\w+)", statement, re.I)
            if create:
                row = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type=? AND name=?",
                    (create[1].lower(), create[2]),
                ).fetchone()
                if row:

                    def normalize(sql):
                        return re.sub(r"\s+", "", sql).rstrip(";")

                    if normalize(row[0]) != normalize(statement):
                        raise sqlite3.OperationalError(f"Conflicting legacy schema: {create[2]}")
                    return
            alter = re.match(r"ALTER TABLE (\w+) ADD COLUMN (\w+) (.+?);?$", statement, re.I | re.S)
            if alter:
                columns = connection.execute(f'PRAGMA table_info("{alter[1]}")').fetchall()
                present = next((tuple(row)[1:] for row in columns if row[1] == alter[2]), None)
                if present:
                    expected = sqlite3.connect(":memory:")
                    try:
                        expected.execute(
                            f"CREATE TABLE expected ({alter[2]} {alter[3].rstrip(';')})"
                        )
                        shape = expected.execute("PRAGMA table_info(expected)").fetchone()[1:]
                    finally:
                        expected.close()
                    if present != shape:
                        raise sqlite3.OperationalError(f"Conflicting legacy column: {alter[2]}")
                    return
        connection.execute(statement)

    def _preserve_legacy_artifacts(self, connection) -> None:
        rows = connection.execute(
            "SELECT a.id,a.path,a.sha256,j.book_id FROM artifacts a JOIN jobs j ON j.id=a.job_id WHERE a.kind='translation'"
        ).fetchall()
        for artifact_id, stored_path, expected, book_id in rows:
            source = Path(self.resolve_path(stored_path))
            digest = hashlib.sha256()
            try:
                with source.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                actual = None
            else:
                actual = digest.hexdigest()
            if actual is None or (expected and actual != expected):
                # Older releases overwrote these bytes. Retain the history but
                # stop presenting it as an available file with a valid hash.
                connection.execute("UPDATE artifacts SET available=0 WHERE id=?", (artifact_id,))
                continue
            destination = self.book_export_dir(book_id) / f"legacy-{artifact_id}{source.suffix}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            connection.execute(
                "UPDATE artifacts SET path=?,sha256=? WHERE id=?",
                (self.store_path(destination), actual, artifact_id),
            )

    def store_path(self, path: str | Path) -> str:
        absolute = Path(path).resolve()
        try:
            return absolute.relative_to(self.root).as_posix()
        except ValueError:
            return str(absolute)

    def resolve_path(self, stored: str) -> str:
        path = Path(stored)
        return str(path if path.is_absolute() else self.root / path)

    def _migrate_owned_paths(self, connection) -> None:
        # Derive old roots from the owned source layout, never from the user's
        # original_path (which is provenance, not a relocatable source).
        roots = {self.root}
        books = connection.execute(
            "SELECT id,stored_source_path,working_source_path,metadata_json FROM books"
        ).fetchall()
        for book in books:
            source = Path(book[1])
            if (
                source.is_absolute()
                and source.parent.name == "source"
                and source.parent.parent.name == book[0]
                and source.parent.parent.parent.name == "library"
            ):
                roots.add(source.parent.parent.parent.parent)

        def portable(value):
            path = Path(value)
            if path.is_absolute():
                for root in sorted(roots, key=lambda item: len(item.parts), reverse=True):
                    try:
                        relative = path.relative_to(root)
                    except ValueError:
                        continue
                    if relative.parts and relative.parts[0] in {
                        "library",
                        "jobs",
                        "exports",
                        "imports",
                        "logs",
                    }:
                        return relative.as_posix()
            return value

        for book in books:
            metadata = json.loads(book[3])
            if "template_path" in metadata:
                metadata["template_path"] = portable(metadata["template_path"])
            connection.execute(
                "UPDATE books SET stored_source_path=?,working_source_path=?,metadata_json=? WHERE id=?",
                (
                    portable(book[1]),
                    portable(book[2]),
                    json.dumps(metadata, ensure_ascii=False),
                    book[0],
                ),
            )
        for row in connection.execute("SELECT id,path FROM artifacts").fetchall():
            connection.execute("UPDATE artifacts SET path=? WHERE id=?", (portable(row[1]), row[0]))
        for row in connection.execute(
            "SELECT id,arguments_json FROM background_operations"
        ).fetchall():
            arguments = json.loads(row[1])
            if arguments.get("output_path"):
                arguments["output_path"] = portable(arguments["output_path"])
                connection.execute(
                    "UPDATE background_operations SET arguments_json=? WHERE id=?",
                    (json.dumps(arguments, ensure_ascii=False), row[0]),
                )

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
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield active
            return
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        active = getattr(self._local, "connection", None)
        if active is not None:
            savepoint = "nested_" + uuid.uuid4().hex
            active.execute(f"SAVEPOINT {savepoint}")
            try:
                yield active
            except BaseException:
                active.execute(f"ROLLBACK TO {savepoint}")
                raise
            finally:
                active.execute(f"RELEASE {savepoint}")
            return
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            self._local.connection = connection
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            self._local.connection = None
            connection.close()

    def book_source_dir(self, book_id: str) -> Path:
        return self.library_dir / book_id / "source"

    def job_artifact_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "artifacts"

    def book_export_dir(self, book_id: str) -> Path:
        return self.exports_dir / book_id
