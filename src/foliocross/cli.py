"""FolioCross command-line interface shared with the desktop application."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .application.migration import discover_wenyi_states, migrate_wenyi_state
from .cli_content import issues_app, revisions_app, segments_app
from .cli_operations import operations_app, require_idle, submit
from .cli_support import CliGroup, json_requested
from .cli_support import emit as _print
from .cli_support import run as _run
from .cli_support import service as _service
from .domain.models import JobConfig, ModelProfile
from .errors import FolioCrossError
from .worker.engine import WorkerEngine

app = typer.Typer(
    cls=CliGroup, no_args_is_help=True, help="FolioCross 本地图书翻译工具；外部脚本请使用 --json。"
)
jobs_app = typer.Typer(no_args_is_help=True, help="任务查询与控制")
glossary_app = typer.Typer(no_args_is_help=True, help="术语表管理")
app.add_typer(jobs_app, name="jobs")
app.add_typer(glossary_app, name="glossary")
app.add_typer(segments_app, name="segments")
app.add_typer(revisions_app, name="revisions")
app.add_typer(issues_app, name="issues")
app.add_typer(operations_app, name="operations")
console = Console()


@app.callback()
def root(
    context: typer.Context,
    workspace: str = typer.Option(None, "--workspace", help="工作区目录；默认 ./workspace"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON；也可以放在具体命令后"),
) -> None:
    context.obj = {"workspace": workspace}


@app.command("app")
def launch_app(context: typer.Context) -> None:
    """启动 PySide6/QML 桌面界面。"""
    from .desktop.app import run_desktop

    raise typer.Exit(run_desktop(_service(context).workspace))


@app.command("import", help="导入图书并创建暂停任务；相同文件复用原任务，不重置配置。")
def import_command(
    context: typer.Context,
    path: str = typer.Argument(..., help="待导入书籍"),
    source_lang: str = typer.Option("auto", "--source-lang"),
    output_format: str = typer.Option("epub", "--output-format"),
    bilingual: bool = typer.Option(False, "--bilingual"),
    soft_budget: float = typer.Option(None, "--soft-budget"),
    hard_budget: float = typer.Option(None, "--hard-budget"),
    max_concurrency: int = typer.Option(4, "--max-concurrency", min=1, max=4),
    rpm: int = typer.Option(None, "--rpm", min=1),
    tpm: int = typer.Option(None, "--tpm", min=1),
    provider: str = typer.Option(None, "--provider", help="deepseek/openai/ollama/vllm"),
    base_url: str = typer.Option(None, "--base-url"),
    model: str = typer.Option(None, "--model"),
    fake: bool = typer.Option(False, "--fake", help="使用离线 Fake 模型创建任务"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = _service(context)
    profile = (
        ModelProfile(
            provider="fake",
            name="Fake",
            translation_model="fake",
            analysis_model="fake",
            repair_model="fake",
            review_model="fake",
        )
        if fake
        else service.default_job_config().profile
    )
    if provider or base_url or model:
        selected_provider = provider or profile.provider
        provider_changed = selected_provider != profile.provider
        profile = replace(
            profile,
            provider=selected_provider,
            base_url=base_url or profile.base_url,
            api_key_env=(
                {
                    "deepseek": "DEEPSEEK_API_KEY",
                    "openai": "OPENAI_API_KEY",
                    "ollama": "",
                    "vllm": "",
                }.get(selected_provider, profile.api_key_env)
            ),
            translation_model=model or profile.translation_model,
            analysis_model=model or profile.analysis_model,
            repair_model=model or profile.repair_model,
            review_model=model or profile.review_model,
            input_price_per_million=(None if provider_changed else profile.input_price_per_million),
            cached_input_price_per_million=(
                None if provider_changed else profile.cached_input_price_per_million
            ),
            output_price_per_million=(
                None if provider_changed else profile.output_price_per_million
            ),
            peak_multiplier=profile.peak_multiplier if selected_provider == "deepseek" else 1.0,
            peak_weekdays_utc=profile.peak_weekdays_utc if selected_provider == "deepseek" else [],
            peak_windows_utc=profile.peak_windows_utc if selected_provider == "deepseek" else [],
            price_source=profile.price_source if selected_provider == "deepseek" else None,
        )
    config = JobConfig(
        source_lang=source_lang,
        output_format=output_format,
        bilingual=bilingual,
        soft_budget=soft_budget,
        hard_budget=hard_budget,
        translation_max_concurrency=max_concurrency,
        requests_per_minute=rpm,
        tokens_per_minute=tpm,
        profile=profile,
    )
    _run(lambda: service.import_book(path, config), json_output=json_output)


@app.command("run", help="开始或恢复整本翻译；默认等待完成，--background 提交到后台。")
def run_command(
    context: typer.Context,
    job_id: str = typer.Argument(..., help="书籍 ID 或任务 ID"),
    no_export: bool = typer.Option(False, "--no-export"),
    preset: str = typer.Option("steady", "--preset"),
    background: bool = typer.Option(False, "--background"),
    prepare_only: bool = typer.Option(False, "--prepare-only", help="只完成译前准备后暂停"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if preset != "steady":
        raise typer.BadParameter("当前只支持 steady（稳妥加速）预设。", param_hint="--preset")
    service = _service(context)

    def action() -> dict[str, Any]:
        resolved = service.repository.resolve_job_id(job_id)
        if prepare_only and no_export:
            raise typer.BadParameter("--prepare-only 无需同时指定 --no-export。")
        if background:
            arguments = {"no_export": True} if no_export else {}
            return submit(service, resolved, "prepare" if prepare_only else "run", arguments)
        require_idle(service, resolved)
        service.control_job(resolved, "run")
        if prepare_only:
            return WorkerEngine(service.workspace).prepare_only(resolved)
        return WorkerEngine(service.workspace).run(resolved, export_when_done=not no_export)

    _run(action, json_output=json_output)


@app.command(
    "review", help="主动深度审校，只生成问题；--estimate 查看估算，--background 后台执行。"
)
def review_command(
    context: typer.Context,
    job_id: str = typer.Argument(...),
    estimate: bool = typer.Option(False, "--estimate", help="只显示预计用量和费用"),
    background: bool = typer.Option(False, "--background"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = _service(context)

    def action():
        resolved = service.repository.resolve_job_id(job_id)
        if estimate and background:
            raise typer.BadParameter("--estimate 与 --background 不能同时使用。")
        if estimate:
            return service.estimate_deep_review(resolved)
        if background:
            return submit(service, resolved, "review")
        require_idle(service, resolved)
        return WorkerEngine(service.workspace).deep_review(resolved)

    _run(action, json_output=json_output)


@app.command("retranslate", help="明确重译指定段落并锁定结果；支持后台执行和版本检查。")
def retranslate_command(
    context: typer.Context,
    job_id: str = typer.Argument(...),
    segment_id: str = typer.Argument(...),
    instruction: str = typer.Option("", "--instruction"),
    background: bool = typer.Option(False, "--background"),
    expected_version: int = typer.Option(None, "--expected-version", min=0),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = _service(context)

    def action():
        resolved = service.repository.resolve_job_id(job_id)
        segment = service.repository.segment_context(segment_id)
        if segment["job_id"] != resolved:
            raise FolioCrossError("segment_job_mismatch", "该段落不属于当前任务。")
        version = segment["version"] if expected_version is None else expected_version
        if version != segment["version"]:
            raise FolioCrossError("segment_version_conflict", "段落已修改，请重新读取后再重译。")
        if background:
            return submit(
                service,
                resolved,
                "retranslate",
                {
                    "segment_id": segment_id,
                    "instruction": instruction,
                    "expected_version": version,
                },
            )
        require_idle(service, resolved)
        return WorkerEngine(service.workspace).retranslate_segment(
            resolved, segment_id, instruction, expected_version=version
        )

    _run(action, json_output=json_output)


@jobs_app.command("list", help="列出任务、进度和费用。")
def jobs_list(context: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    rows = _service(context).repository.list_jobs()
    if json_output or json_requested.get():
        _print({"ok": True, "jobs": rows}, True)
        return
    table = Table("任务", "书名", "状态", "阶段", "进度", "费用")
    for row in rows:
        table.add_row(
            row["id"],
            row["title"],
            row["status"],
            row["stage"],
            f"{row['completed_segments']}/{row['total_segments']}",
            f"{row['actual_cost']:.4f} {row['currency']}",
        )
    console.print(table)


@jobs_app.command("status", help="读取任务、章节、问题、用量、产物和当前后台操作。")
def jobs_status(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
) -> None:
    service = _service(context)
    job_id = service.repository.resolve_job_id(job_id)
    _run(
        lambda: {
            "ok": True,
            "job": service.repository.get_job(job_id),
            "chapters": service.repository.chapters_for_job(job_id),
            "issues": service.repository.list_issues(job_id),
            "usage": service.repository.usage_summary(job_id),
            "artifacts": service.repository.list_artifacts(job_id),
            "background_operation": service.repository.active_background_operation(job_id),
        },
        json_output=json_output,
    )


def _control(context: typer.Context, job_id: str, action: str, json_output: bool) -> None:
    def control():
        service = _service(context)
        resolved = service.repository.resolve_job_id(job_id)
        result = service.control_job(resolved, action)
        removed = service.repository.cancel_queued_background_operation(resolved)
        if removed:
            service.repository.update_job(
                resolved,
                status="cancelled" if action == "cancel" else "paused",
                message="排队操作已取消" if action == "cancel" else "排队操作已暂停",
            )
        return {**result, "queued_operation_stopped": removed}

    _run(control, json_output=json_output)


@jobs_app.command("pause", help="请求安全暂停翻译；排队中的操作直接停止。请查询状态确认生效。")
def jobs_pause(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
) -> None:
    _control(context, job_id, "pause", json_output)


@jobs_app.command("resume", help="从已保存进度继续翻译；支持 --background。")
def jobs_resume(
    context: typer.Context,
    job_id: str,
    json_output: bool = typer.Option(False, "--json"),
    background: bool = typer.Option(False, "--background"),
) -> None:
    service = _service(context)

    def action() -> dict[str, Any]:
        resolved = service.repository.resolve_job_id(job_id)
        if background:
            return submit(service, resolved, "run")
        require_idle(service, resolved)
        service.control_job(resolved, "resume")
        return WorkerEngine(service.workspace).run(resolved)

    _run(action, json_output=json_output)


@jobs_app.command("cancel", help="请求取消翻译；已保存译文保留，排队中的操作直接停止。")
def jobs_cancel(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
) -> None:
    _control(context, job_id, "cancel", json_output)


@app.command("export", help="从已保存译文重新导出；支持指定路径和 --background。")
def export_command(
    context: typer.Context,
    job_id: str,
    format_name: str = typer.Option(None, "--format"),
    output: str = typer.Option(None, "--output"),
    background: bool = typer.Option(False, "--background"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def action():
        service = _service(context)
        resolved = service.repository.resolve_job_id(job_id)
        selected_format = (
            format_name or service.repository.get_job(resolved)["config"]["output_format"]
        ).lower()
        if selected_format not in {"epub", "docx", "html", "txt", "md", "markdown"}:
            raise FolioCrossError("unsupported_output", f"不支持的输出格式：{selected_format}")
        target = str(Path(output).resolve()) if output else None
        if background:
            arguments = {"format_name": selected_format}
            if target:
                arguments["output_path"] = target
            return submit(service, resolved, "export", arguments)
        require_idle(service, resolved)
        result = WorkerEngine(service.workspace).export_only(resolved, selected_format, target)
        return {**result, "path": result["output"]}

    _run(action, json_output=json_output)


@jobs_app.command("chapters", help="按原书顺序列出章节 ID、标题和翻译进度。")
def jobs_chapters(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
):
    def action():
        repo = _service(context).repository
        resolved = repo.resolve_job_id(job_id)
        return {"ok": True, "job_id": resolved, "chapters": repo.chapters_for_job(resolved)}

    _run(action, json_output=json_output)


@jobs_app.command("stop", help="立即停止该任务的后台 Worker，保留已保存进度供恢复。")
def jobs_stop(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
):
    def action():
        from .worker.scheduler import ensure_scheduler

        service = _service(context)
        repo = service.repository
        resolved = repo.resolve_job_id(job_id)
        if repo.cancel_queued_background_operation(resolved):
            service.control_job(resolved, "pause")
            repo.update_job(resolved, status="paused", message="排队操作已停止")
            return {"ok": True, "job_id": resolved, "stop_requested": True}
        requested = repo.request_background_operation_cancel(resolved)
        if requested:
            ensure_scheduler(service.workspace)
        return {"ok": True, "job_id": resolved, "stop_requested": requested}

    _run(action, json_output=json_output)


@glossary_app.command("list", help="读取当前术语表与冻结版本信息，无需导出文件。")
def glossary_list(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
):
    def action():
        repo = _service(context).repository
        resolved = repo.resolve_job_id(job_id)
        return {
            "ok": True,
            "job_id": resolved,
            "terms": repo.list_glossary(resolved),
            "snapshot": repo.glossary_snapshot(resolved),
        }

    _run(action, json_output=json_output)


@glossary_app.command("export", help="将术语表导出为 UTF-8 JSON 文件。")
def glossary_export(
    context: typer.Context,
    job_id: str = typer.Argument(..., help="书籍 ID 或任务 ID"),
    output: str = typer.Option(None, "--output"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def action() -> dict[str, Any]:
        resolved = _service(context).repository.resolve_job_id(job_id)
        terms = _service(context).repository.list_glossary(resolved)
        target = Path(output or f"glossary-{resolved}.json").resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            raise FolioCrossError("glossary_export_failed", f"术语表无法写入：{target}") from error
        return {"ok": True, "job_id": resolved, "path": str(target), "terms": len(terms)}

    _run(action, json_output=json_output)


@glossary_app.command("import", help="导入 JSON 术语数组；不会自动替换运行任务已冻结的术语版本。")
def glossary_import(
    context: typer.Context,
    job_id: str,
    path: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def action() -> dict[str, Any]:
        resolved = _service(context).repository.resolve_job_id(job_id)
        source = Path(path).resolve()
        try:
            terms = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise FolioCrossError("glossary_file_missing", f"找不到术语文件：{source}") from error
        except json.JSONDecodeError as error:
            raise FolioCrossError("glossary_json_invalid", "术语文件不是有效的 JSON。") from error
        if not isinstance(terms, list):
            raise FolioCrossError("glossary_shape_invalid", "术语文件顶层必须是数组。")
        _service(context).repository.upsert_glossary_terms(resolved, terms)
        return {"ok": True, "job_id": resolved, "terms": len(terms)}

    _run(action, json_output=json_output)


@glossary_app.command("refresh", help="明确刷新冻结术语版本；运行中的任务需要先暂停。")
def glossary_refresh(
    context: typer.Context,
    job_id: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = _service(context)
    _run(
        lambda: service.refresh_glossary_snapshot(service.repository.resolve_job_id(job_id)),
        json_output=json_output,
    )


@app.command("migrate-wenyi", help="列出旧状态；指定 --state 和 --source 后只读复制导入。")
def migrate_wenyi(
    context: typer.Context,
    wenyi_root: str = typer.Argument(...),
    state_dir: str = typer.Option(None, "--state", help="具体 state/<书名> 目录"),
    source: str = typer.Option(None, "--source", help="与状态匹配的原始书籍"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if bool(state_dir) != bool(source):
        raise typer.BadParameter("--state 和 --source 必须一起提供。")
    if not state_dir:
        _run(
            lambda: {
                "ok": True,
                "states": discover_wenyi_states(wenyi_root),
                "migration_started": False,
            },
            json_output=json_output,
        )
        return
    _run(
        lambda: migrate_wenyi_state(_service(context), state_dir=state_dir, source_path=source),
        json_output=json_output,
    )


@app.command("doctor", help="检查本机依赖和模型配置；仅 --live-model 会发起真实连接检查。")
def doctor(
    context: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
    live_model: bool = typer.Option(False, "--live-model", help="发起一次极小的真实连接检查"),
) -> None:
    service = _service(context)

    def action() -> dict[str, Any]:
        result = service.doctor()
        if live_model:
            result["model_connection"] = service.test_model_connection()
        return result

    _run(action, json_output=json_output)


def main() -> None:
    if os_name_is_windows():
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")
    app()


def os_name_is_windows() -> bool:
    return sys.platform.startswith("win")


if __name__ == "__main__":
    main()
