"""Durable background operation scheduler independent from the desktop process."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..domain.models import DesiredState, JobStatus
from ..infrastructure.repository import Repository
from ..infrastructure.workspace import Workspace

ACTIVE_JOB_STATES = {
    JobStatus.PREPARING.value,
    JobStatus.TRANSLATING.value,
    JobStatus.QUALITY_CHECK.value,
    JobStatus.EXPORTING.value,
}


@contextmanager
def scheduler_lock(workspace: Workspace) -> Iterator[bool]:
    """Take the one-byte cross-process scheduler lock without blocking."""

    workspace.root.mkdir(parents=True, exist_ok=True)
    path = workspace.root / "scheduler.lock"
    stream = path.open("a+b")
    acquired = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"1")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                acquired = False
        else:  # pragma: no cover - Windows-first application
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                acquired = False
        yield acquired
    finally:
        if acquired:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - Windows-first application
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not process:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    try:  # pragma: no cover - Windows-first application
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _terminate_pid(pid: int | None) -> None:
    if not _pid_alive(pid):
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return


def _worker_arguments(operation: dict) -> list[str]:
    arguments = operation["arguments"]
    result = [
        sys.executable,
        "-m",
        "foliocross.worker",
        "--workspace",
        operation["workspace"],
        "--job",
        operation["job_id"],
    ]
    action = operation["action"]
    if action == "prepare":
        result.append("--prepare-only")
    elif action == "review":
        result.append("--review")
    elif action == "retranslate":
        result.extend(["--retranslate", str(arguments["segment_id"])])
        instruction = str(arguments.get("instruction", ""))
        if instruction:
            result.extend(["--instruction", instruction])
        if arguments.get("expected_version") is not None:
            result.extend(["--expected-version", str(arguments["expected_version"])])
    elif action == "export":
        result.extend(["--export-format", str(arguments["format_name"])])
        if arguments.get("output_path"):
            result.extend(["--output", str(arguments["output_path"])])
    elif action != "run":
        raise ValueError(f"Unsupported operation action: {action}")
    if action == "run" and arguments.get("no_export"):
        result.append("--no-export")
    return result


def _creation_flags(*, detached: bool = False) -> int:
    if os.name != "nt":
        return 0
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    if detached:
        flags |= subprocess.DETACHED_PROCESS
    return flags


def ensure_scheduler(workspace: Workspace) -> int:
    """Start a detached scheduler; a duplicate exits immediately on the singleton lock."""

    workspace.initialize()
    log_path = workspace.logs_dir / "scheduler.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "foliocross.worker.scheduler",
                "--workspace",
                str(workspace.root),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=_creation_flags(detached=True),
            start_new_session=os.name != "nt",
        )
    return int(process.pid)


def _operation_log_tail(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return lines[-1].strip() if lines else ""


def _recorded_worker_exit_code(path: Path) -> int | None:
    """Recover a detached worker's result after the scheduler itself was restarted."""

    line = _operation_log_tail(path)
    if not line:
        return None
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    if value.get("type") == "worker.result" and value.get("payload", {}).get("ok") is True:
        return 0
    if value.get("ok") is False or "error" in value:
        return 1
    return None


def run_scheduler(
    workspace: Workspace,
    *,
    poll_interval: float = 0.2,
    idle_grace_seconds: float = 1.5,
) -> int:
    """Run until all durable operations finish and the queue remains idle."""

    repository = Repository(workspace)
    with scheduler_lock(workspace) as acquired:
        if not acquired:
            return 0
        managed: dict[str, subprocess.Popen] = {}
        logs: dict[str, Path] = {}
        idle_since: float | None = None
        while True:
            running = repository.background_operations("running")
            for operation in running:
                operation_id = operation["id"]
                process = managed.get(operation_id)
                if operation["cancel_requested"]:
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    else:
                        _terminate_pid(operation.get("pid"))
                    repository.finish_background_operation(
                        operation_id, status="cancelled", exit_code=-1
                    )
                    repository.set_desired_state(operation["job_id"], DesiredState.PAUSE)
                    repository.update_job(
                        operation["job_id"],
                        status=JobStatus.INTERRUPTED.value,
                        message="Worker 被立即停止，可以从已完成批次继续",
                    )
                    managed.pop(operation_id, None)
                    continue

                exit_code = process.poll() if process is not None else None
                alive = exit_code is None and (
                    process is not None
                    or _pid_alive(operation.get("pid"))
                    or repository._job_lock_is_held(operation["job_id"])
                )
                if alive:
                    continue
                job = repository.get_job(operation["job_id"])
                log_path = logs.get(operation_id) or (
                    workspace.logs_dir / f"operation-{operation_id}.log"
                )
                if process is None:
                    exit_code = _recorded_worker_exit_code(log_path)
                    if exit_code is None:
                        exit_code = 1
                    resumable_states = ACTIVE_JOB_STATES | {JobStatus.QUEUED.value}
                    if exit_code != 0 and job["status"] in resumable_states:
                        repository.set_desired_state(operation["job_id"], DesiredState.PAUSE)
                        repository.update_job(
                            operation["job_id"],
                            status=JobStatus.INTERRUPTED.value,
                            message="后台 Worker 意外退出，可以从已完成批次继续",
                        )
                        repository.emit_event(
                            operation["job_id"],
                            "job.interrupted",
                            {"reason": "worker_process_missing"},
                        )
                        job = repository.get_job(operation["job_id"])
                terminal = (
                    "cancelled"
                    if job["status"] == JobStatus.CANCELLED.value
                    else ("completed" if exit_code == 0 else "failed")
                )
                error = _operation_log_tail(log_path) if terminal == "failed" else ""
                if terminal == "failed" and not error:
                    error = "后台 Worker 意外退出，可以从已完成批次继续"
                repository.finish_background_operation(
                    operation_id,
                    status=terminal,
                    exit_code=exit_code,
                    error_message=error or None,
                )
                managed.pop(operation_id, None)

            active_count = len(repository.background_operations("running"))
            limit = max(1, min(4, int(repository.get_setting("active_task_limit", 1) or 1)))
            capacity = max(0, limit - active_count)
            if capacity:
                for operation in repository.background_operations("queued"):
                    if capacity <= 0:
                        break
                    if (
                        operation["action"] in {"run", "prepare"}
                        and repository.desired_state(operation["job_id"]) != DesiredState.RUN.value
                    ):
                        repository.finish_background_operation(
                            operation["id"], status="cancelled", exit_code=None
                        )
                        continue
                    operation["workspace"] = str(workspace.root)
                    log_path = workspace.logs_dir / f"operation-{operation['id']}.log"
                    try:
                        with log_path.open("ab") as log:
                            process = subprocess.Popen(
                                _worker_arguments(operation),
                                stdin=subprocess.DEVNULL,
                                stdout=log,
                                stderr=subprocess.STDOUT,
                                close_fds=True,
                                creationflags=_creation_flags(),
                                start_new_session=os.name != "nt",
                            )
                    except (KeyError, OSError, ValueError) as error:
                        repository.finish_background_operation(
                            operation["id"],
                            status="failed",
                            exit_code=None,
                            error_message=str(error),
                        )
                        continue
                    repository.mark_background_operation_running(operation["id"], process.pid)
                    managed[operation["id"]] = process
                    logs[operation["id"]] = log_path
                    capacity -= 1

            pending = repository.background_operations("queued", "running")
            if pending:
                idle_since = None
            elif idle_since is None:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since >= idle_grace_seconds:
                return 0
            time.sleep(max(0.02, poll_interval))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    raise SystemExit(run_scheduler(Workspace(args.workspace)))


if __name__ == "__main__":
    main()
