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
from .application.service import FolioCrossService
from .domain.models import JobConfig, ModelProfile
from .errors import FolioCrossError
from .infrastructure.workspace import Workspace
from .worker.engine import WorkerEngine

app = typer.Typer(no_args_is_help=True, help="FolioCross 本地图书翻译工具")
jobs_app = typer.Typer(no_args_is_help=True, help="任务查询与控制")
glossary_app = typer.Typer(no_args_is_help=True, help="术语表管理")
app.add_typer(jobs_app, name="jobs")
app.add_typer(glossary_app, name="glossary")
console = Console()


def _service(context: typer.Context) -> FolioCrossService:
    return context.obj


def _print(value: Any, json_output: bool) -> None:
    if json_output:
        console.print_json(json.dumps(value, ensure_ascii=False))
    else:
        console.print(value)


def _run(action, *, json_output: bool) -> None:
    try:
        _print(action(), json_output)
    except FolioCrossError as error:
        if json_output:
            console.print_json(json.dumps(error.as_dict(), ensure_ascii=False))
        else:
            console.print(f"[red]错误：{error.message}[/]")
        raise typer.Exit(1) from None
    except Exception as error:
        wrapped = FolioCrossError(
            "operation_failed",
            str(error) or "操作失败。",
            details={"exception": type(error).__name__},
        )
        if json_output:
            console.print_json(json.dumps(wrapped.as_dict(), ensure_ascii=False))
        else:
            console.print(f"[red]错误：{wrapped.message}[/]")
        raise typer.Exit(1) from None


@app.callback()
def root(
    context: typer.Context,
    workspace: str = typer.Option(None, "--workspace", help="工作区目录；默认 ./workspace"),
) -> None:
    context.obj = FolioCrossService(Workspace(workspace) if workspace else Workspace.default())


@app.command("app")
def launch_app(context: typer.Context) -> None:
    """启动 PySide6/QML 桌面界面。"""
    from .desktop.app import run_desktop

    raise typer.Exit(run_desktop(_service(context).workspace))


@app.command("import")
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


@app.command("run")
def run_command(
    context: typer.Context,
    job_id: str = typer.Argument(..., help="书籍 ID 或任务 ID"),
    no_export: bool = typer.Option(False, "--no-export"),
    preset: str = typer.Option("steady", "--preset"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if preset != "steady":
        raise typer.BadParameter("当前只支持 steady（稳妥加速）预设。", param_hint="--preset")
    service = _service(context)

    def action() -> dict[str, Any]:
        resolved = service.repository.resolve_job_id(job_id)
        service.control_job(resolved, "run")
        return WorkerEngine(service.workspace).run(resolved, export_when_done=not no_export)

    _run(action, json_output=json_output)


@app.command("review")
def review_command(
    context: typer.Context,
    job_id: str = typer.Argument(...),
    estimate: bool = typer.Option(False, "--estimate", help="只显示预计用量和费用"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = _service(context)
    action = (
        (lambda: service.estimate_deep_review(job_id))
        if estimate
        else (lambda: WorkerEngine(service.workspace).deep_review(job_id))
    )
    _run(action, json_output=json_output)


@app.command("retranslate")
def retranslate_command(
    context: typer.Context,
    job_id: str = typer.Argument(...),
    segment_id: str = typer.Argument(...),
    instruction: str = typer.Option("", "--instruction"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = _service(context)
    _run(
        lambda: WorkerEngine(service.workspace).retranslate_segment(
            job_id, segment_id, instruction
        ),
        json_output=json_output,
    )


@jobs_app.command("list")
def jobs_list(context: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    rows = _service(context).repository.list_jobs()
    if json_output:
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


@jobs_app.command("status")
def jobs_status(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
) -> None:
    service = _service(context)
    _run(
        lambda: {
            "ok": True,
            "job": service.repository.get_job(job_id),
            "chapters": service.repository.chapters_for_job(job_id),
            "issues": service.repository.list_issues(job_id),
            "usage": service.repository.usage_summary(job_id),
            "artifacts": service.repository.list_artifacts(job_id),
        },
        json_output=json_output,
    )


def _control(context: typer.Context, job_id: str, action: str, json_output: bool) -> None:
    _run(lambda: _service(context).control_job(job_id, action), json_output=json_output)


@jobs_app.command("pause")
def jobs_pause(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
) -> None:
    _control(context, job_id, "pause", json_output)


@jobs_app.command("resume")
def jobs_resume(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
) -> None:
    service = _service(context)

    def action() -> dict[str, Any]:
        resolved = service.repository.resolve_job_id(job_id)
        service.control_job(resolved, "resume")
        return WorkerEngine(service.workspace).run(resolved)

    _run(action, json_output=json_output)


@jobs_app.command("cancel")
def jobs_cancel(
    context: typer.Context, job_id: str, json_output: bool = typer.Option(False, "--json")
) -> None:
    _control(context, job_id, "cancel", json_output)


@app.command("export")
def export_command(
    context: typer.Context,
    job_id: str,
    format_name: str = typer.Option(None, "--format"),
    output: str = typer.Option(None, "--output"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(lambda: _service(context).export(job_id, format_name, output), json_output=json_output)


@glossary_app.command("export")
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


@glossary_app.command("import")
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


@glossary_app.command("refresh")
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


@app.command("migrate-wenyi")
def migrate_wenyi(
    context: typer.Context,
    wenyi_root: str = typer.Argument(...),
    state_dir: str = typer.Option(None, "--state", help="具体 state/<书名> 目录"),
    source: str = typer.Option(None, "--source", help="与状态匹配的原始书籍"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if not state_dir or not source:
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


@app.command("doctor")
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
