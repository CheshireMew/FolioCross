from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from foliocross.application.service import FolioCrossService
from foliocross.cli import app
from foliocross.infrastructure.workspace import Workspace
from foliocross.worker.scheduler import run_scheduler


@pytest.fixture
def cli(tmp_path):
    root = tmp_path / "workspace"
    runner = CliRunner()

    def invoke(*args, exit_code=0):
        result = runner.invoke(app, ["--workspace", str(root), "--json", *map(str, args)])
        assert result.exit_code == exit_code, result.output
        payload = json.loads(result.stdout)
        assert not result.stderr
        return payload

    source = tmp_path / "书籍.md"
    source.write_text(
        "# One\n\nFirst paragraph.\n\nSecond paragraph.\n\n# Two\n\nThird paragraph.",
        encoding="utf-8",
    )
    imported = invoke("import", source, "--fake", "--output-format", "txt")
    return invoke, imported, FolioCrossService(Workspace(root))


@pytest.mark.parametrize(
    "args",
    [
        ["unknown", "--json"],
        ["operations", "wait", "missing", "--timeout", "nan", "--json"],
        ["run", "--json"],
        ["segments", "edit", "x", "--json"],
        ["segments", "list", "x", "--limit", "0", "--json"],
        ["run", "x", "--preset", "unknown", "--json"],
        ["jobs", "list", "--unknown", "--json"],
        ["migrate-wenyi", "unused", "--state", "unused", "--json"],
    ],
)
def test_argument_errors_are_json(tmp_path, args):
    workspace = tmp_path / "must-not-exist"
    result = CliRunner().invoke(app, ["--workspace", str(workspace), *args])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_arguments"
    assert not result.stderr
    assert not workspace.exists()


def test_all_commands_have_help_and_help_does_not_create_workspace(tmp_path):
    def inspect(command, prefix):
        assert command.help, prefix
        result = CliRunner().invoke(
            app, ["--workspace", str(tmp_path / "unused"), *prefix, "--help"]
        )
        assert result.exit_code == 0, result.output
        for name, child in getattr(command, "commands", {}).items():
            inspect(child, [*prefix, name])

    inspect(get_command(app), [])
    assert not (tmp_path / "unused").exists()


def test_content_pagination_edit_restore_and_export(cli, tmp_path):
    invoke, imported, svc = cli
    job = imported["job_id"]
    book = imported["book_id"]
    chapters = invoke("jobs", "chapters", book)["chapters"]
    assert chapters
    first = invoke("segments", "list", book, "--limit", 1)
    second = invoke("segments", "list", book, "--offset", first["next_offset"], "--limit", 1)
    assert first["segments"][0]["id"] != second["segments"][0]["id"]
    assert first["total"] > 1
    segment = invoke("segments", "list", job, "--query", "First paragraph")["segments"][0]
    assert invoke("segments", "show", segment["id"])["segment"]["job_id"] == job
    assert (
        invoke("segments", "list", job, "--chapter", "missing", exit_code=1)["error"]["code"]
        == "chapter_not_found"
    )
    text = tmp_path / "译文.txt"
    original = "这是一段译文。\n" + "长文本不会因为终端宽度而被改变。" * 100
    text.write_text(original, encoding="utf-8-sig")
    edited = invoke(
        "segments",
        "edit",
        segment["id"],
        "--text-file",
        text,
        "--expected-version",
        segment["version"],
    )
    assert edited["locked"]
    stale = invoke(
        "segments",
        "edit",
        segment["id"],
        "--text-file",
        text,
        "--expected-version",
        segment["version"],
        exit_code=1,
    )
    assert stale["error"]["code"] == "segment_version_conflict"
    assert invoke("segments", "show", segment["id"])["segment"]["target_text"] == original
    history = invoke("revisions", "list", segment["id"])["revisions"]
    text.write_text("改后的译文。", encoding="utf-8")
    newer = invoke(
        "segments",
        "edit",
        segment["id"],
        "--text-file",
        text,
        "--expected-version",
        edited["version"],
    )
    invoke(
        "revisions",
        "restore",
        history[0]["id"],
        "--expected-version",
        edited["version"],
        exit_code=1,
    )
    restored = invoke(
        "revisions", "restore", history[0]["id"], "--expected-version", newer["version"]
    )
    assert restored["version"] == newer["version"] + 1
    invoke("run", job)
    assert svc.repository.segment(segment["id"])["target_text"] == original
    output = tmp_path / "译文导出.txt"
    exported = invoke("export", job, "--format", "txt", "--output", output)
    assert exported["artifact_id"]
    assert original in Path(exported["path"]).read_text(encoding="utf-8")


def test_issues_accept_requires_current_version_and_dismiss_preserves_text(cli):
    invoke, imported, svc = cli
    job = imported["job_id"]
    segment = invoke("segments", "list", job)["segments"][0]
    issue_id = svc.repository.create_issue(
        job,
        segment_id=segment["id"],
        category="style",
        severity="warning",
        message="调整表达",
        suggestion="修改建议",
    )
    assert invoke("issues", "show", issue_id)["issue"]["suggestion"] == "修改建议"
    invoke("issues", "accept", issue_id, "--expected-version", segment["version"] + 1, exit_code=1)
    assert svc.repository.issue(issue_id)["status"] == "open"
    accepted = invoke("issues", "accept", issue_id, "--expected-version", segment["version"])
    assert accepted["version"] == segment["version"] + 1
    repeated = invoke(
        "issues", "accept", issue_id, "--expected-version", accepted["version"], exit_code=1
    )
    assert repeated["error"]["code"] == "issue_already_resolved"
    assert not invoke("issues", "list", job, "--open")["issues"]
    another = svc.repository.create_issue(
        job,
        segment_id=segment["id"],
        category="style",
        severity="warning",
        message="另一建议",
        suggestion="不应用",
    )
    invoke("issues", "dismiss", another)
    assert svc.repository.segment(segment["id"])["target_text"] == "修改建议"


def test_background_deduplication_pause_cancel_wait_and_recovery(cli, monkeypatch):
    invoke, imported, svc = cli
    job = imported["job_id"]
    monkeypatch.setattr("foliocross.cli_operations.ensure_scheduler", lambda _: 123)
    queued = invoke("run", job, "--background")
    assert invoke("run", job, "--background")["operation_id"] == queued["operation_id"]
    assert (
        invoke("review", job, "--background", exit_code=1)["error"]["code"]
        == "background_operation_active"
    )
    assert invoke("run", job, exit_code=1)["error"]["code"] == "background_operation_active"
    assert invoke("operations", "wait", queued["operation_id"], "--timeout", 0)["timed_out"]
    assert invoke("operations", "recover")["pending_operations"] == 1
    assert invoke("jobs", "status", job)["background_operation"]["id"] == queued["operation_id"]
    assert invoke("jobs", "pause", job)["queued_operation_stopped"]
    assert invoke("operations", "status", queued["operation_id"])["terminal"]
    resumed = invoke("jobs", "resume", job, "--background")
    assert resumed["operation_id"] != queued["operation_id"]
    invoke("jobs", "cancel", job)
    assert invoke("jobs", "status", job)["job"]["status"] == "cancelled"
    invoke("jobs", "resume", job, "--background")
    assert invoke("jobs", "stop", job)["stop_requested"]
    assert not invoke("jobs", "stop", job)["stop_requested"]
    assert len(invoke("operations", "list", "--job", job)["operations"]) == 3
    assert not svc.repository.background_operations("queued", "running")


def test_background_worker_modes(cli, tmp_path, monkeypatch):
    invoke, imported, svc = cli
    job = imported["job_id"]
    monkeypatch.setattr("foliocross.cli_operations.ensure_scheduler", lambda _: 123)

    def execute(*args):
        operation = invoke(*args, "--background")
        assert run_scheduler(svc.workspace, poll_interval=0.02, idle_grace_seconds=0.02) == 0
        result = invoke("operations", "status", operation["operation_id"])
        assert result["operation"]["status"] == "completed", result
        return result

    prepared = execute("run", job, "--prepare-only")
    assert prepared["job"]["status"] == "paused"
    assert not any(a["kind"] == "translation" for a in prepared["artifacts"])
    translated = execute("run", job, "--no-export")
    assert translated["job"]["status"] == "ready"
    assert not any(a["kind"] == "translation" for a in translated["artifacts"])
    execute("review", job)
    segment = invoke("segments", "list", job)["segments"][0]
    execute(
        "retranslate",
        job,
        segment["id"],
        "--instruction",
        "保持简洁",
        "--expected-version",
        segment["version"],
    )
    output = tmp_path / "后台导出.txt"
    exported = execute("export", job, "--format", "txt", "--output", output)
    assert output.is_file()
    version = next(
        a
        for a in exported["artifacts"]
        if a.get("metadata", {}).get("delivery_path") == str(output)
    )
    assert Path(version["path"]).read_bytes() == output.read_bytes()


def test_background_retranslation_rejects_edit_after_submission(cli, tmp_path, monkeypatch):
    invoke, imported, svc = cli
    job = imported["job_id"]
    monkeypatch.setattr("foliocross.cli_operations.ensure_scheduler", lambda _: 123)
    segment = invoke("segments", "list", job)["segments"][0]
    queued = invoke("retranslate", job, segment["id"], "--background")
    text = tmp_path / "manual.txt"
    text.write_text("保留最新编辑", encoding="utf-8")
    invoke(
        "segments",
        "edit",
        segment["id"],
        "--text-file",
        text,
        "--expected-version",
        segment["version"],
    )
    run_scheduler(svc.workspace, poll_interval=0.02, idle_grace_seconds=0.02)
    result = invoke("operations", "wait", queued["operation_id"], "--timeout", 0)
    assert result["terminal"] and not result["timed_out"]
    assert result["operation"]["status"] == "failed"
    assert "segment_version_conflict" in result["operation"]["error_message"]
    assert svc.repository.segment(segment["id"])["target_text"] == "保留最新编辑"


def test_real_cli_process_background_survives_exit(cli):
    invoke, imported, svc = cli
    args = [sys.executable, "-m", "foliocross.cli", "--workspace", str(svc.workspace.root)]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    started = subprocess.run(
        [*args, "run", imported["job_id"], "--background", "--json"],
        capture_output=True,
        encoding="utf-8",
        timeout=10,
        env=env,
    )
    assert started.returncode == 0, started.stderr + started.stdout
    operation = json.loads(started.stdout)
    result = invoke("operations", "wait", operation["operation_id"], "--timeout", 20)
    assert result["operation"]["status"] == "completed", result
    assert result["job"]["status"] == "completed"
    assert any(Path(a["path"]).is_file() for a in result["artifacts"] if a["kind"] == "translation")


def test_scheduler_start_failure_leaves_recoverable_operation(cli, monkeypatch):
    invoke, imported, svc = cli

    def fail(_):
        raise OSError("cannot start")

    monkeypatch.setattr("foliocross.cli_operations.ensure_scheduler", fail)
    error = invoke("run", imported["job_id"], "--background", exit_code=1)["error"]
    assert error["code"] == "scheduler_start_failed"
    operation_id = error["details"]["operation_id"]
    assert svc.repository.background_operation(operation_id)["status"] == "queued"
    monkeypatch.setattr("foliocross.cli_operations.ensure_scheduler", lambda _: 123)
    assert invoke("run", imported["job_id"], "--background")["operation_id"] == operation_id
    invoke("jobs", "pause", imported["job_id"])


def test_edit_rejects_missing_epub_markers(tmp_path):
    from conftest import write_sample_epub

    runner = CliRunner()
    prefix = ["--workspace", str(tmp_path / "workspace"), "--json"]
    source = write_sample_epub(tmp_path / "source.epub")
    imported = runner.invoke(app, [*prefix, "import", str(source), "--fake"])
    assert imported.exit_code == 0
    job_id = json.loads(imported.stdout)["job_id"]
    listed = runner.invoke(app, [*prefix, "segments", "list", job_id])
    segment = next(s for s in json.loads(listed.stdout)["segments"] if s["markers"])
    text = tmp_path / "edit.txt"
    text.write_text("丢失格式标记的译文", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            *prefix,
            "segments",
            "edit",
            segment["id"],
            "--text-file",
            str(text),
            "--expected-version",
            str(segment["version"]),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "invalid_markers"
    shown = runner.invoke(app, [*prefix, "segments", "show", segment["id"]])
    assert json.loads(shown.stdout)["segment"]["version"] == segment["version"]


def test_issue_accept_rolls_back_both_revision_and_issue(cli):
    invoke, imported, svc = cli
    segment = invoke("segments", "list", imported["job_id"])["segments"][0]
    issue_id = svc.repository.create_issue(
        imported["job_id"],
        segment_id=segment["id"],
        category="style",
        severity="warning",
        message="调整表达",
        suggestion="原建议",
    )
    with svc.workspace.transaction() as connection:
        connection.execute("""CREATE TRIGGER reject_revision BEFORE INSERT ON segment_revisions
                            BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END""")
    invoke("issues", "accept", issue_id, "--expected-version", segment["version"], exit_code=1)
    assert svc.repository.issue(issue_id)["status"] == "open"
    assert svc.repository.segment(segment["id"])["version"] == segment["version"]
    assert not svc.repository.segment_revisions(segment["id"])


def test_retranslation_preserves_edit_during_model_call(cli, monkeypatch):
    from foliocross.worker.engine import LLMRuntime

    invoke, imported, svc = cli
    segment = invoke("segments", "list", imported["job_id"])["segments"][0]
    original = LLMRuntime.call_json

    def concurrent_edit(runtime, **kwargs):
        result = original(runtime, **kwargs)
        if kwargs["stage"] == "retranslation":
            svc.edit_segment(
                segment["id"], "模型运行时保存的人工修改", expected_version=segment["version"]
            )
        return result

    monkeypatch.setattr(LLMRuntime, "call_json", concurrent_edit)
    error = invoke("retranslate", imported["job_id"], segment["id"], exit_code=1)
    assert error["error"]["code"] == "segment_version_conflict"
    assert svc.repository.segment(segment["id"])["target_text"] == "模型运行时保存的人工修改"
