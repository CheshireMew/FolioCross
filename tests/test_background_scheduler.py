from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from foliocross.application.service import FolioCrossService
from foliocross.domain.models import JobConfig, ModelProfile
from foliocross.worker.scheduler import run_scheduler


def fake_config() -> JobConfig:
    return JobConfig(
        profile=ModelProfile(
            id="fake",
            name="Fake",
            provider="fake",
            translation_model="fake",
            analysis_model="fake",
            repair_model="fake",
            review_model="fake",
        )
    )


def import_fake_job(service: FolioCrossService, path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return service.import_book(str(path), fake_config())["job_id"]


def test_scheduler_runs_durable_queue_in_order(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    first = import_fake_job(service, tmp_path / "first.md", "# First\n\nFirst paragraph.")
    second = import_fake_job(service, tmp_path / "second.md", "# Second\n\nSecond paragraph.")
    service.repository.set_setting("active_task_limit", 1)
    for job_id in (first, second):
        service.control_job(job_id, "run")
        service.repository.update_job(job_id, status="queued", message="queued")
        service.repository.enqueue_background_operation(job_id, "run")

    assert run_scheduler(workspace, poll_interval=0.02, idle_grace_seconds=0.05) == 0

    assert service.repository.get_job(first)["status"] == "completed"
    assert service.repository.get_job(second)["status"] == "completed"
    operations = service.repository.background_operations("completed")
    assert len(operations) == 2
    assert operations[0]["finished_at"] <= operations[1]["started_at"]


def test_detached_scheduler_survives_starting_process_exit(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    job_id = import_fake_job(
        service,
        tmp_path / "detached.md",
        "# Detached\n\nThe desktop process exits before this translation finishes.",
    )
    service.control_job(job_id, "run")
    service.repository.update_job(job_id, status="queued", message="queued")
    service.repository.enqueue_background_operation(job_id, "run")
    script = (
        "from foliocross.infrastructure.workspace import Workspace;"
        "from foliocross.worker.scheduler import ensure_scheduler;"
        f"print(ensure_scheduler(Workspace({str(workspace.root)!r})))"
    )
    started = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert int(started.stdout.strip()) > 0

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        completed = service.repository.background_operations("completed")
        if service.repository.get_job(job_id)["status"] == "completed" and completed:
            break
        time.sleep(0.05)
    assert service.repository.get_job(job_id)["status"] == "completed"
    operation = completed[-1]
    assert operation["job_id"] == job_id
    assert operation["pid"]


def test_scheduler_force_stop_terminates_worker_and_preserves_resume_state(
    workspace, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("FOLIOCROSS_FAKE_DELAY_SECONDS", "2")
    service = FolioCrossService(workspace)
    job_id = import_fake_job(
        service,
        tmp_path / "force-stop.md",
        "# Force stop\n\nA paragraph that keeps the fake request active long enough to stop.",
    )
    service.control_job(job_id, "run")
    service.repository.update_job(job_id, status="queued", message="queued")
    service.repository.enqueue_background_operation(job_id, "run")
    thread = threading.Thread(
        target=run_scheduler,
        args=(workspace,),
        kwargs={"poll_interval": 0.02, "idle_grace_seconds": 0.05},
    )
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        operation = service.repository.active_background_operation(job_id)
        if operation and operation["status"] == "running":
            break
        time.sleep(0.02)
    assert operation["status"] == "running"
    assert service.repository.request_background_operation_cancel(job_id) is True
    thread.join(timeout=10)
    assert not thread.is_alive()
    job = service.repository.get_job(job_id)
    assert job["status"] == "interrupted"
    assert job["desired_state"] == "pause"
    cancelled = service.repository.background_operations("cancelled")
    assert len(cancelled) == 1
    assert cancelled[0]["job_id"] == job_id


def test_scheduler_recovers_a_stale_running_operation_as_interrupted(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    job_id = import_fake_job(
        service,
        tmp_path / "stale-worker.md",
        "# Stale worker\n\nA committed checkpoint must remain resumable after a crash.",
    )
    service.control_job(job_id, "run")
    service.repository.update_job(job_id, status="translating", message="running")
    operation = service.repository.enqueue_background_operation(job_id, "run")
    service.repository.mark_background_operation_running(operation["id"], 2_147_483_646)

    assert run_scheduler(workspace, poll_interval=0.02, idle_grace_seconds=0.05) == 0

    job = service.repository.get_job(job_id)
    assert job["status"] == "interrupted"
    assert job["desired_state"] == "pause"
    failed = service.repository.background_operations("failed")
    assert len(failed) == 1
    assert failed[0]["job_id"] == job_id
    assert failed[0]["exit_code"] == 1
    assert "意外退出" in failed[0]["error_message"]
    assert any(
        event["event_type"] == "job.interrupted" for event in service.repository.list_events(job_id)
    )


def test_scheduler_recovers_a_completed_orphan_from_the_worker_log(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    job_id = import_fake_job(
        service,
        tmp_path / "completed-orphan.md",
        "# Completed orphan\n\nThe scheduler restarts after its Worker exits cleanly.",
    )
    operation = service.repository.enqueue_background_operation(job_id, "run")
    service.repository.mark_background_operation_running(operation["id"], 2_147_483_646)
    service.repository.update_job(
        job_id,
        status="completed",
        stage="completed",
        message="complete",
        finished=True,
    )
    log_path = workspace.logs_dir / f"operation-{operation['id']}.log"
    log_path.write_text(
        '{"protocol_version":1,"type":"worker.result","payload":{"ok":true}}\n',
        encoding="utf-8",
    )

    assert run_scheduler(workspace, poll_interval=0.02, idle_grace_seconds=0.05) == 0

    completed = service.repository.background_operations("completed")
    assert len(completed) == 1
    assert completed[0]["job_id"] == job_id
    assert completed[0]["exit_code"] == 0
    assert service.repository.get_job(job_id)["status"] == "completed"
