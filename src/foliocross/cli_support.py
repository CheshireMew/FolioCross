"""Shared CLI output and error handling, including argument parsing failures."""

from __future__ import annotations

import json
import sys
from contextvars import ContextVar

import typer
from typer.core import TyperGroup

try:
    from typer import _click as click
except ImportError:  # Typer versions before Click was bundled.
    import click

from .errors import FolioCrossError

json_requested = ContextVar("cli_json_requested", default=False)


class CliGroup(TyperGroup):
    def main(self, args=None, prog_name=None, complete_var=None, standalone_mode=True, **extra):
        arguments = list(sys.argv[1:] if args is None else args)
        options = arguments[: arguments.index("--")] if "--" in arguments else arguments
        token = json_requested.set("--json" in options)
        try:
            try:
                result = super().main(
                    args=arguments,
                    prog_name=prog_name,
                    complete_var=complete_var,
                    standalone_mode=False,
                    **extra,
                )
            except click.ClickException as error:
                if json_requested.get():
                    emit(
                        FolioCrossError("invalid_arguments", error.format_message()).as_dict(), True
                    )
                else:
                    error.show()
                result = error.exit_code
            except (click.Abort, KeyboardInterrupt):
                emit(
                    FolioCrossError(
                        "interrupted", "命令已中断，请查询任务状态后再恢复。"
                    ).as_dict(),
                    json_requested.get(),
                )
                result = 130
            except Exception as error:
                emit(error_payload(error), json_requested.get())
                result = 1
            if standalone_mode:
                raise SystemExit(result if isinstance(result, int) else 0)
            return result
        finally:
            json_requested.reset(token)


def error_payload(error):
    if not isinstance(error, FolioCrossError):
        error = FolioCrossError(
            "operation_failed",
            str(error) or "操作失败。",
            details={"exception": type(error).__name__},
        )
    return error.as_dict()


def emit(value, json_output=False):
    if json_output or json_requested.get():
        # Plain UTF-8 JSON: terminal width and Rich markup must not affect the protocol.
        typer.echo(json.dumps(value, ensure_ascii=False))
    else:
        from rich.console import Console

        Console().print(value)


def run(action, *, json_output=False):
    try:
        result = action()
    except click.ClickException:
        raise
    except Exception as error:
        emit(error_payload(error), json_output)
        raise typer.Exit(1) from None
    emit(result, json_output)
    if isinstance(result, dict) and result.get("ok") is False:
        raise typer.Exit(1)


def service(context):
    # Resolve lazily so command help and invalid arguments never initialize a workspace.
    root = context.find_root()
    if not isinstance(root.obj, dict):
        return root.obj
    if "service" not in root.obj:
        from .application.service import FolioCrossService
        from .infrastructure.workspace import Workspace

        path = root.obj["workspace"]
        root.obj["service"] = FolioCrossService(Workspace(path) if path else Workspace.default())
    return root.obj["service"]


def read_text(path):
    from pathlib import Path

    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise FolioCrossError("text_file_unreadable", f"无法读取 UTF-8 文件：{path}") from error
