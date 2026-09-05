"""Public content inspection and explicit revision commands."""

from __future__ import annotations

import typer

from .cli_support import read_text, run, service
from .errors import FolioCrossError
from .infrastructure.formats.markers import validate_markers

segments_app = typer.Typer(no_args_is_help=True, help="分页读取原译文并保存锁定修改")
revisions_app = typer.Typer(no_args_is_help=True, help="查看历史并恢复为新的锁定版本")
issues_app = typer.Typer(no_args_is_help=True, help="查看和处理审校问题")


@segments_app.command("list", help="按原书顺序分页读取段落；可按章节或原译文中的文本筛选。")
def segment_list(
    context: typer.Context,
    job_id: str,
    chapter: str = typer.Option(None, "--chapter", help="章节 ID"),
    offset: int = typer.Option(0, min=0),
    limit: int = typer.Option(50, min=1, max=200),
    query: str = typer.Option("", "--query", help="区分大小写的文本搜索"),
    json_output: bool = typer.Option(False, "--json"),
):
    def action():
        repo = service(context).repository
        return repo.segment_page(
            repo.resolve_job_id(job_id), chapter_id=chapter, offset=offset, limit=limit, query=query
        )

    run(action, json_output=json_output)


@segments_app.command("show", help="读取一个段落的原文、译文、版本号、标记和全书/章节上下文。")
def segment_show(
    context: typer.Context, segment_id: str, json_output: bool = typer.Option(False, "--json")
):
    run(
        lambda: {"ok": True, "segment": service(context).repository.segment_context(segment_id)},
        json_output=json_output,
    )


@segments_app.command("edit", help="从 UTF-8 文件保存译文并锁定；必须提供读取时的版本号。")
def segment_edit(
    context: typer.Context,
    segment_id: str,
    text_file: str = typer.Option(..., "--text-file", help="完整译文文件；保留原有 FC 标记"),
    expected_version: int = typer.Option(..., "--expected-version", min=0),
    json_output: bool = typer.Option(False, "--json"),
):
    def action():
        svc = service(context)
        text = read_text(text_file)
        segment = svc.repository.segment(segment_id)
        problems = validate_markers(text, segment["markers"])
        if problems:
            raise FolioCrossError(
                "invalid_markers",
                "译文中的保护标记不完整或顺序有误，请保留原有 FC 标记。",
                details={"issues": problems},
            )
        return svc.edit_segment(segment_id, text, expected_version=expected_version)

    run(action, json_output=json_output)


@revisions_app.command("list", help="按版本从新到旧读取一个段落的历史译文。")
def revision_list(
    context: typer.Context, segment_id: str, json_output: bool = typer.Option(False, "--json")
):
    def action():
        repo = service(context).repository
        segment = repo.segment(segment_id)
        return {
            "ok": True,
            "segment_id": segment_id,
            "version": segment["version"],
            "revisions": repo.segment_revisions(segment_id),
        }

    run(action, json_output=json_output)


@revisions_app.command("restore", help="恢复历史译文为一个新版本；旧版本全部保留。")
def revision_restore(
    context: typer.Context,
    revision_id: str,
    expected_version: int = typer.Option(..., "--expected-version", min=0),
    json_output: bool = typer.Option(False, "--json"),
):
    run(
        lambda: service(context).restore_revision(revision_id, expected_version=expected_version),
        json_output=json_output,
    )


@issues_app.command("list", help="读取任务审校问题；--open 只显示未处理问题。")
def issue_list(
    context: typer.Context,
    job_id: str,
    open_only: bool = typer.Option(False, "--open"),
    json_output: bool = typer.Option(False, "--json"),
):
    def action():
        repo = service(context).repository
        resolved = repo.resolve_job_id(job_id)
        return {
            "ok": True,
            "job_id": resolved,
            "issues": repo.list_issues(resolved, include_resolved=not open_only),
        }

    run(action, json_output=json_output)


@issues_app.command("show", help="读取一个审校问题及其建议。")
def issue_show(
    context: typer.Context, issue_id: str, json_output: bool = typer.Option(False, "--json")
):
    run(
        lambda: {"ok": True, "issue": service(context).repository.issue(issue_id)},
        json_output=json_output,
    )


@issues_app.command("accept", help="明确应用建议并锁定译文；可用 UTF-8 文件提供修订后的建议。")
def issue_accept(
    context: typer.Context,
    issue_id: str,
    expected_version: int = typer.Option(..., "--expected-version", min=0),
    text_file: str = typer.Option(None, "--text-file"),
    json_output: bool = typer.Option(False, "--json"),
):
    run(
        lambda: service(context).apply_issue_suggestion(
            issue_id, read_text(text_file) if text_file else None, expected_version=expected_version
        ),
        json_output=json_output,
    )


@issues_app.command("dismiss", help="忽略一个审校问题，保留译文。")
def issue_dismiss(
    context: typer.Context, issue_id: str, json_output: bool = typer.Option(False, "--json")
):
    def action():
        service(context).repository.resolve_issue(issue_id, "dismissed")
        return {"ok": True, "issue_id": issue_id, "status": "dismissed"}

    run(action, json_output=json_output)
