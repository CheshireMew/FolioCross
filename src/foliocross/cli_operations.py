"""Durable background execution for external command-line callers."""

from __future__ import annotations

import math
import time
from pathlib import Path

import typer

from .cli_support import run, service
from .errors import FolioCrossError
from .worker.scheduler import ensure_scheduler

operations_app = typer.Typer(no_args_is_help=True, help="查询后台操作、有限等待和恢复调度")


def submit(svc, job_id, action, arguments=None):
    job_id = svc.repository.resolve_job_id(job_id)
    operation = svc.repository.enqueue_background_operation(
        job_id, action, arguments, activate=True
    )
    try:
        ensure_scheduler(svc.workspace)
    except OSError as error:
        raise FolioCrossError(
            "scheduler_start_failed",
            "操作已保存，但后台调度器未启动；请执行 operations recover。",
            details={"operation_id": operation["id"], "job_id": job_id},
        ) from error
    return {"ok": True, "job_id": job_id, "operation_id": operation["id"], "operation": operation}


def require_idle(svc, job_id):
    if svc.repository.active_background_operation(job_id):
        raise FolioCrossError(
            "background_operation_active", "任务已有后台操作，请查询 operations 或等待结束。"
        )


def snapshot(svc, operation_id):
    operation = svc.repository.background_operation(operation_id)
    terminal = operation["status"] in {"completed", "failed", "cancelled"}
    return {
        "ok": True,
        "operation": operation,
        "terminal": terminal,
        "job": svc.repository.get_job(operation["job_id"]),
        "artifacts": svc.repository.list_artifacts(operation["job_id"]),
        "log_path": str(Path(svc.workspace.logs_dir) / f"operation-{operation_id}.log"),
    }


@operations_app.command("list", help="列出持久化后台操作；可按任务筛选。")
def operation_list(
    context: typer.Context,
    job_id: str = typer.Option(None, "--job"),
    json_output: bool = typer.Option(False, "--json"),
):
    def action():
        repo = service(context).repository
        resolved = repo.resolve_job_id(job_id) if job_id else None
        return {
            "ok": True,
            "operations": [
                item
                for item in repo.background_operations()
                if resolved is None or item["job_id"] == resolved
            ],
        }

    run(action, json_output=json_output)


@operations_app.command("status", help="读取操作状态、任务状态、产物和日志路径。")
def operation_status(
    context: typer.Context, operation_id: str, json_output: bool = typer.Option(False, "--json")
):
    run(lambda: snapshot(service(context), operation_id), json_output=json_output)


@operations_app.command("wait", help="最多等待 60 秒；超时只返回当前状态，不停止后台操作。")
def operation_wait(
    context: typer.Context,
    operation_id: str,
    timeout: float = typer.Option(30, min=0, max=60),
    json_output: bool = typer.Option(False, "--json"),
):
    if not math.isfinite(timeout):
        raise typer.BadParameter("等待时间必须是 0 到 60 秒之间的有限数值。")

    def action():
        svc = service(context)
        deadline = time.monotonic() + timeout
        while True:
            result = snapshot(svc, operation_id)
            remaining = deadline - time.monotonic()
            if result["terminal"] or remaining <= 0:
                return {**result, "timed_out": not result["terminal"]}
            time.sleep(min(0.2, remaining))

    run(action, json_output=json_output)


@operations_app.command(
    "recover", help="重新启动调度器，接管已保存的排队和运行操作；不会新建翻译任务。"
)
def operation_recover(context: typer.Context, json_output: bool = typer.Option(False, "--json")):
    def action():
        svc = service(context)
        pending = svc.repository.background_operations("queued", "running")
        if pending:
            ensure_scheduler(svc.workspace)
        return {"ok": True, "pending_operations": len(pending)}

    run(action, json_output=json_output)
