"""Regression coverage for the FC-A01–FC-A10 audit findings."""

import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from foliocross.infrastructure.workspace import Workspace


def test_workspace_copy_resolves_own_files_in_new_root(workspace, tmp_path):
    import shutil

    from foliocross.application.service import FolioCrossService
    from foliocross.domain.models import JobConfig

    source = tmp_path / "source.html"
    source.write_text("<html><body><p>Original paragraph</p></body></html>", encoding="utf-8")
    service = FolioCrossService(workspace)
    imported = service.import_book(str(source), JobConfig())
    chapter = service.repository.chapters_for_job(imported["job_id"])[0]
    segment = service.repository.segments_for_chapter(chapter["id"])[0]
    service.edit_segment(segment["id"], "Translated paragraph")
    exported = service.export(imported["job_id"], "html")
    restored_root = tmp_path / "restored"
    shutil.copytree(workspace.root, restored_root)
    # Retain all files; make the old paths unavailable without deleting anything.
    workspace.root.rename(tmp_path / "original-archived")
    restored = FolioCrossService(Workspace(restored_root))
    book = restored.repository.get_book(imported["book_id"])
    for field in ("stored_source_path", "working_source_path"):
        assert Path(book[field]).is_relative_to(restored_root)
        assert Path(book[field]).is_file()
    for artifact in restored.repository.list_artifacts(imported["job_id"]):
        assert Path(artifact["path"]).is_relative_to(restored_root)
        assert Path(artifact["path"]).is_file()
    again = restored.export(imported["job_id"], "html")
    assert "Translated paragraph" in Path(again["path"]).read_text(encoding="utf-8")
    assert exported["path"] != again["path"]


def test_failed_wenyi_import_retries_without_partial_database(workspace, tmp_path):
    import hashlib
    import json

    from foliocross.application.migration import migrate_wenyi_state
    from foliocross.application.service import FolioCrossService

    source = tmp_path / "legacy.txt"
    source.write_text("Legacy paragraph.", encoding="utf-8")
    state = tmp_path / "state"
    (state / "chapters").mkdir(parents=True)
    (state / "manifest.json").write_text(
        json.dumps(
            {
                "fmt": "text",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "chapters": [{"index": 0}],
            }
        ),
        encoding="utf-8",
    )
    (state / "chapters/ch0.json").write_text(
        json.dumps(
            {"segments": [{"source": "Legacy paragraph.", "target": "Translated paragraph."}]}
        ),
        encoding="utf-8",
    )
    (state / "analysis.json").write_text("{invalid", encoding="utf-8")
    service = FolioCrossService(workspace)
    with pytest.raises(json.JSONDecodeError):
        migrate_wenyi_state(service, state_dir=str(state), source_path=str(source))
    assert service.repository.list_books() == []
    (state / "analysis.json").write_text("{}", encoding="utf-8")
    before = {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    report = migrate_wenyi_state(service, state_dir=str(state), source_path=str(source))
    assert report["translated_segments"] == 1
    with workspace.session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM segment_revisions").fetchone()[0] == 1
    assert before == {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()}


def test_schema_upgrade_rolls_back_version_and_ddl(tmp_path, monkeypatch):
    class InterruptedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO schema_migrations") and parameters == (2,):
                raise sqlite3.OperationalError("injected interruption")
            return super().execute(sql, parameters)

    workspace = Workspace(tmp_path / "interrupted")
    workspace.root.mkdir()
    original = workspace.connect
    monkeypatch.setattr(
        workspace,
        "connect",
        lambda: sqlite3.connect(
            workspace.db_path, isolation_level=None, factory=InterruptedConnection
        ),
    )
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        workspace.initialize()
    monkeypatch.setattr(workspace, "connect", original)
    # Check the failed transaction before recovery can reconcile legacy DDL.
    with workspace.session() as connection:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )
    workspace.initialize()
    with workspace.session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 5
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("partial_version", [1, 2, 3, 4, 5])
def test_recovers_legacy_partial_schema(tmp_path, partial_version):
    workspace = Workspace(tmp_path / "legacy")
    workspace.root.mkdir()
    with workspace.session() as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        migrations = sorted(
            files("foliocross.infrastructure.migrations").iterdir(), key=lambda p: p.name
        )
        for resource in migrations:
            if resource.name.endswith(".sql"):
                version = int(resource.name.split("_")[0])
                if version > partial_version:
                    break
                sql = resource.read_text(encoding="utf-8")
                if version == partial_version:
                    # The old autocommit implementation could stop after any statement.
                    connection.execute(sql.split(";")[0])
                else:
                    connection.executescript(sql)
                    connection.execute(
                        "INSERT INTO schema_migrations VALUES (?, 'legacy')", (version,)
                    )
    workspace.initialize()
    workspace.initialize()
    with workspace.session() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 5


def test_concurrent_workspace_startup_is_serialized(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    root = tmp_path / "concurrent"
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: Workspace(root).initialize(), range(4)))
    with Workspace(root).session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 8
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_v5_restore_rebases_files_and_reconciles_overwritten_history(workspace, tmp_path):
    import json
    import shutil

    from foliocross.application.service import FolioCrossService
    from foliocross.infrastructure.repository import sha256_file

    source = tmp_path / "old.html"
    source.write_text("<html><body><p>Original</p></body></html>", encoding="utf-8")
    service = FolioCrossService(workspace)
    imported = service.import_book(str(source))
    job_id = imported["job_id"]
    segment = service.repository.segments_for_chapter(
        service.repository.chapters_for_job(job_id)[0]["id"]
    )[0]
    service.edit_segment(segment["id"], "Translated")
    old_output = workspace.book_export_dir(imported["book_id"]) / "old.html"
    old_output.parent.mkdir(parents=True)
    old_output.write_text("old content", encoding="utf-8")
    lost = service.repository.add_artifact(
        job_id, kind="translation", format_name="html", path=str(old_output)
    )
    old_output.write_text("latest content", encoding="utf-8")
    valid = service.repository.add_artifact(
        job_id, kind="translation", format_name="html", path=str(old_output)
    )
    external = tmp_path / "external.txt"
    external.write_text("external", encoding="utf-8")
    service.repository.add_artifact(job_id, kind="reference", format_name="txt", path=str(external))
    restored = Workspace(tmp_path / "v5-restored")
    restored.root.mkdir()
    for name in ("library", "jobs", "exports", "imports"):
        shutil.copytree(workspace.root / name, restored.root / name)
    # Build the shipped v5 schema and copy rows using its actual columns.
    with restored.session() as old, workspace.session() as current:
        old.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)"
        )
        for resource in sorted(
            files("foliocross.infrastructure.migrations").iterdir(), key=lambda p: p.name
        ):
            if resource.name.endswith(".sql") and int(resource.name.split("_")[0]) <= 5:
                old.executescript(resource.read_text(encoding="utf-8"))
                old.execute(
                    "INSERT INTO schema_migrations VALUES (?, 'legacy')",
                    (int(resource.name.split("_")[0]),),
                )
        tables = [
            r[0]
            for r in old.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('schema_migrations','sqlite_sequence')"
            )
        ]
        for table in tables:
            columns = [r[1] for r in old.execute(f"PRAGMA table_info({table})")]
            for row in current.execute(f"SELECT {','.join(columns)} FROM {table}"):
                values = dict(zip(columns, row))
                if table == "books":
                    for key in ("stored_source_path", "working_source_path"):
                        values[key] = workspace.resolve_path(values[key])
                    metadata = json.loads(values["metadata_json"])
                    metadata.pop("extraction_version", None)
                    values["metadata_json"] = json.dumps(metadata)
                if table == "artifacts":
                    values["path"] = workspace.resolve_path(values["path"])
                old.execute(
                    f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    list(values.values()),
                )
    workspace.root.rename(tmp_path / "v5-source-archived")
    consumer = FolioCrossService(restored)
    book = consumer.repository.get_book(imported["book_id"])
    assert Path(book["working_source_path"]).is_relative_to(restored.root)
    artifacts = consumer.repository.list_artifacts(job_id)
    assert lost not in {a["id"] for a in artifacts}
    kept = next(a for a in artifacts if a["id"] == valid)
    assert Path(kept["path"]).is_relative_to(restored.root)
    assert kept["sha256"] == sha256_file(kept["path"])
    assert next(a for a in artifacts if a["kind"] == "reference")["path"] == str(external)
    result = consumer.export(job_id, "html")
    assert "Translated" in Path(result["path"]).read_text(encoding="utf-8")


def test_wenyi_late_failure_rolls_back_glossary_usage_and_versions(
    workspace, tmp_path, monkeypatch
):
    import hashlib
    import json

    from foliocross.application import migration
    from foliocross.application.service import FolioCrossService

    source = tmp_path / "legacy.txt"
    source.write_text("Alice speaks.", encoding="utf-8")
    state = tmp_path / "state"
    (state / "chapters").mkdir(parents=True)
    (state / "manifest.json").write_text(
        json.dumps(
            {
                "fmt": "text",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "chapters": [{"index": 0}],
            }
        ),
        encoding="utf-8",
    )
    (state / "chapters/ch0.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "source": "Alice speaks.",
                        "target_before_polish": "Alice draft",
                        "target": "Alice final",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (state / "usage.json").write_text(
        json.dumps({"prompt_tokens": 321, "completion_tokens": 27}), encoding="utf-8"
    )
    with sqlite3.connect(state / "glossary.db") as connection:
        connection.execute("CREATE TABLE glossary(source TEXT,target TEXT)")
        connection.execute("INSERT INTO glossary VALUES ('Alice','Name')")
    original_state = {p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()}
    service = FolioCrossService(workspace)

    def fail_after_all_writes(*args):
        raise OSError("injected output-copy failure")

    with monkeypatch.context() as patch:
        patch.setattr(migration, "_copy_legacy_outputs", fail_after_all_writes)
        with pytest.raises(OSError, match="injected"):
            migration.migrate_wenyi_state(service, state_dir=str(state), source_path=str(source))
    with workspace.session() as connection:
        for table in (
            "books",
            "jobs",
            "segments",
            "segment_revisions",
            "glossary_terms",
            "usage_events",
            "llm_requests",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    report = migration.migrate_wenyi_state(service, state_dir=str(state), source_path=str(source))
    with workspace.session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM segment_revisions").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM glossary_terms").fetchone()[0] == 1
        assert (
            connection.execute("SELECT SUM(prompt_tokens) FROM usage_events").fetchone()[0] == 321
        )
    assert report["translated_segments"] == 1
    assert original_state == {
        p.relative_to(state): p.read_bytes() for p in state.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("manual_edit", [False, True, "glossary"])
def test_old_partial_wenyi_retry_preserves_user_changes(
    workspace, tmp_path, monkeypatch, manual_edit
):
    import hashlib
    import json

    from foliocross.application import migration
    from foliocross.application.service import FolioCrossService
    from foliocross.errors import FolioCrossError

    source = tmp_path / "legacy.txt"
    source.write_text("Legacy paragraph.", encoding="utf-8")
    state = tmp_path / "state"
    (state / "chapters").mkdir(parents=True)
    (state / "manifest.json").write_text(
        json.dumps(
            {
                "fmt": "text",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "chapters": [{"index": 0}],
            }
        ),
        encoding="utf-8",
    )
    (state / "chapters/ch0.json").write_text(
        json.dumps(
            {"segments": [{"source": "Legacy paragraph.", "target": "Translated paragraph."}]}
        ),
        encoding="utf-8",
    )
    (state / "analysis.json").write_text("{bad", encoding="utf-8")
    service = FolioCrossService(workspace)
    # Exercise the shipped sequence without the newly added outer transaction.
    with pytest.raises(json.JSONDecodeError):
        migration._migrate_wenyi_state(service, state_dir=str(state), source_path=str(source))
    book = service.repository.list_books()[0]
    job_id = book["latest_job_id"]
    segment = service.repository.segments_for_chapter(
        service.repository.chapters_for_job(job_id)[0]["id"]
    )[0]
    assert segment["version"] == 1
    (state / "analysis.json").write_text("{}", encoding="utf-8")
    if manual_edit:
        if manual_edit == "glossary":
            service.update_glossary(job_id, "Added term", "My chosen term")
        else:
            service.edit_segment(segment["id"], "My protected edit")
        with pytest.raises(FolioCrossError, match="只有尚未完成"):
            migration.migrate_wenyi_state(service, state_dir=str(state), source_path=str(source))
        if manual_edit == "glossary":
            assert service.repository.list_glossary(job_id)[0]["target"] == "My chosen term"
        else:
            assert service.repository.segment(segment["id"])["target_text"] == "My protected edit"
    else:
        result = migration.migrate_wenyi_state(
            service, state_dir=str(state), source_path=str(source)
        )
        assert result["job_id"] == job_id
        assert service.repository.segment(segment["id"])["version"] == 1
        assert len(service.repository.segment_revisions(segment["id"])) == 1
