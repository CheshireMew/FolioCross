from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

from conftest import write_sample_epub

from foliocross.application.service import FolioCrossService
from foliocross.domain.models import JobConfig, ModelProfile
from foliocross.infrastructure.llm import FakeClient, ModelResponse, ModelUsage
from foliocross.worker.engine import (
    AdaptiveLimiter,
    LLMRuntime,
    WorkerEngine,
    WorkerEventEmitter,
)


def fake_config(output: str = "txt") -> JobConfig:
    return JobConfig(
        output_format=output,
        translation_start_concurrency=2,
        translation_max_concurrency=4,
        profile=ModelProfile(
            id="fake",
            name="Fake",
            provider="fake",
            base_url="http://fake",
            api_key_env="",
            translation_model="fake",
            analysis_model="fake",
            repair_model="fake",
            review_model="fake",
            input_price_per_million=1.0,
            output_price_per_million=2.0,
        ),
    )


def test_fake_worker_runs_prepare_translate_quality_export(workspace, tmp_path: Path):
    source = tmp_path / "worker.md"
    source.write_text(
        "# One\n\nFirst paragraph has enough words to translate.\n\n# Two\n\nSecond paragraph also has useful words.",
        encoding="utf-8",
    )
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    events = []
    result = WorkerEngine(workspace, event_sink=events.append).run(job_id)
    assert result["status"] == "completed"
    assert Path(result["output"]).is_file()
    job = service.repository.get_job(job_id)
    assert job["completed_segments"] == job["total_segments"]
    assert {event["type"] for event in events} >= {
        "job.started",
        "stage.changed",
        "usage.recorded",
        "job.completed",
    }
    usage = service.repository.usage_summary(job_id)
    assert usage["total"]["calls"] >= 4
    assert usage["total"]["cost"] > 0


def test_epub_worker_preserves_template_resources(workspace, tmp_path: Path):
    source = write_sample_epub(tmp_path / "source.epub")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config("epub"))["job_id"]
    result = WorkerEngine(workspace).run(job_id)
    with zipfile.ZipFile(result["output"]) as archive:
        assert "OEBPS/style.css" in archive.namelist()
        assert "OEBPS/cover.png" in archive.namelist()
        chapter = archive.read("OEBPS/chapter.xhtml").decode("utf-8")
        assert 'href="#n1"' in chapter
        assert "⟦FC:" not in chapter


def test_committed_translation_reexports_to_all_output_formats(workspace, tmp_path: Path):
    source = tmp_path / "outputs.md"
    source.write_text("# Chapter\n\nA complete export paragraph.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    WorkerEngine(workspace).run(job_id, export_when_done=False)
    engine = WorkerEngine(workspace)
    for format_name in ("epub", "docx", "html", "txt", "md"):
        result = engine.export_only(job_id, format_name)
        assert Path(result["output"]).is_file()


def test_generated_epub_uses_translated_heading_without_duplicate(workspace, tmp_path: Path):
    source = tmp_path / "heading.md"
    source.write_text("# Original Heading\n\nBody paragraph.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config("epub"))["job_id"]
    chapter = service.repository.chapters_for_job(job_id)[0]
    heading, body = service.repository.segments_for_chapter(chapter["id"])
    service.repository.save_segment_revision(heading["id"], "中文标题", origin="manual", lock=True)
    service.repository.save_segment_revision(body["id"], "中文正文。", origin="manual", lock=True)

    result = WorkerEngine(workspace).run(job_id)
    with zipfile.ZipFile(result["output"]) as archive:
        chapter_xhtml = archive.read("OEBPS/chapter-1.xhtml").decode("utf-8")
        nav_xhtml = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
    assert chapter_xhtml.count("中文标题") == 2  # title metadata and visible h1
    assert "Original Heading" not in chapter_xhtml
    assert ">中文标题</a>" in nav_xhtml
    assert "<dc:title>中文标题</dc:title>" in opf


def test_resume_skips_already_committed_segment(workspace, tmp_path: Path):
    source = tmp_path / "resume.txt"
    source.write_text("First paragraph.\n\nSecond paragraph.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    chapter = service.repository.chapters_for_job(job_id)[0]
    first = service.repository.segments_for_chapter(chapter["id"])[0]
    service.repository.save_segment_revision(first["id"], "人工完成", origin="manual", lock=True)
    WorkerEngine(workspace).run(job_id)
    assert service.repository.segment(first["id"])["target_text"] == "人工完成"
    assert len(service.repository.segment_revisions(first["id"])) == 1


def test_cancel_preserves_imported_data(workspace, tmp_path: Path):
    source = tmp_path / "cancel.txt"
    source.write_text("Keep this source.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    service.control_job(job_id, "cancel")
    # Worker.run deliberately changes a direct run request back to RUN, so exercise the persisted
    # control contract without starting a new run.
    assert service.repository.desired_state(job_id) == "cancel"
    assert Path(service.repository.get_job(job_id)["stored_source_path"]).is_file()


def test_retranslate_locked_segment_creates_a_new_locked_revision(workspace, tmp_path: Path):
    source = tmp_path / "retranslate.txt"
    source.write_text("A complete paragraph for retranslation.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    WorkerEngine(workspace).run(job_id, export_when_done=False)
    chapter = service.repository.chapters_for_job(job_id)[0]
    segment = service.repository.segments_for_chapter(chapter["id"])[0]
    service.edit_segment(segment["id"], "人工译文", expected_version=segment["version"])
    result = WorkerEngine(workspace).retranslate_segment(job_id, segment["id"], "保持简洁")
    assert result["version"] == 3
    stored = service.repository.segment(segment["id"])
    assert stored["locked"] is True
    revisions = service.repository.segment_revisions(segment["id"])
    assert revisions[0]["origin"] == "retranslation"
    assert revisions[0]["instruction"] == "保持简洁"


def test_prepare_only_freezes_context_then_regular_run_resumes(workspace, tmp_path: Path):
    source = tmp_path / "prepare.md"
    source.write_text(
        "# One\n\nA complete paragraph.\n\n# Two\n\nAnother paragraph.", encoding="utf-8"
    )
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    prepared = WorkerEngine(workspace).prepare_only(job_id)
    assert prepared["status"] == "prepared"
    job = service.repository.get_job(job_id)
    assert job["status"] == "paused"
    assert job["stage"] == "prepared"
    assert job["book_context"]["overview"]
    preparation_calls = service.repository.usage_summary(job_id)["total"]["calls"]
    WorkerEngine(workspace).run(job_id, export_when_done=False)
    stages = service.repository.usage_summary(job_id)["by_stage_model"]
    assert preparation_calls == 3
    assert sum(row["calls"] for row in stages if row["stage"] == "preparation") == 3


def test_explicit_deep_review_creates_issue_without_overwriting(
    workspace, tmp_path: Path, monkeypatch
):
    source = tmp_path / "review.txt"
    source.write_text("A complete paragraph for review.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    WorkerEngine(workspace).run(job_id, export_when_done=False)
    chapter = service.repository.chapters_for_job(job_id)[0]
    segment = service.repository.segments_for_chapter(chapter["id"])[0]
    before = segment["target_text"]

    class ReviewClient:
        def complete(self, **kwargs):
            payload = json.loads(kwargs["user"])
            reviewed = payload["review_segments"][0]
            return ModelResponse(
                json.dumps(
                    {
                        "issues": [
                            {
                                "segment_id": reviewed["id"],
                                "category": "accuracy",
                                "severity": "warning",
                                "message": "需要核对语义。",
                                "evidence": {"source": reviewed["source"]},
                                "suggestion": "建议译文。",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                ModelUsage(prompt_tokens=20, completion_tokens=10),
            )

    monkeypatch.setattr("foliocross.worker.engine.FakeClient", ReviewClient)
    result = WorkerEngine(workspace).deep_review(job_id)
    assert result["issues_created"] == 1
    assert service.repository.segment(segment["id"])["target_text"] == before
    issue = service.repository.list_issues(job_id)[0]
    service.apply_issue_suggestion(issue["id"])
    assert service.repository.segment(segment["id"])["target_text"] == "建议译文。"


def test_hard_budget_pauses_before_first_request(workspace, tmp_path: Path):
    source = tmp_path / "budget.txt"
    source.write_text("A paragraph that should not be sent.", encoding="utf-8")
    config = fake_config()
    config.hard_budget = 0.0
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), config)["job_id"]
    result = WorkerEngine(workspace).run(job_id)
    assert result["status"] == "paused"
    assert service.repository.usage_summary(job_id)["total"]["calls"] == 0


def test_soft_budget_warns_once_and_continues(workspace, tmp_path: Path):
    source = tmp_path / "soft-budget.txt"
    source.write_text("A paragraph that should still be translated.", encoding="utf-8")
    config = fake_config()
    config.soft_budget = 0.000001
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), config)["job_id"]
    events = []
    result = WorkerEngine(workspace, event_sink=events.append).run(job_id)

    warnings = [
        event
        for event in events
        if event["type"] == "warning.raised"
        and event["payload"].get("code") == "soft_budget_reached"
    ]
    assert result["status"] == "completed"
    assert len(warnings) == 1
    assert service.repository.usage_summary(job_id)["total"]["calls"] > 1


def test_429_retries_and_lowers_then_recovers_concurrency(workspace, tmp_path: Path):
    source = tmp_path / "rate-limit.txt"
    source.write_text("A paragraph.", encoding="utf-8")
    config = fake_config()
    config.max_retries = 1
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), config)["job_id"]
    service.control_job(job_id, "run")
    events = []
    emitter = WorkerEventEmitter(service.repository, events.append)
    runtime = LLMRuntime(service.repository, job_id, config, emitter)

    class FlakyClient:
        calls = 0

        def complete(self, **kwargs):
            del kwargs
            self.calls += 1
            if self.calls == 1:
                error = RuntimeError("429")
                error.status_code = 429
                error.response = SimpleNamespace(headers={"retry-after": "0"})
                raise error
            return ModelResponse("{}", ModelUsage(prompt_tokens=3, completion_tokens=1))

    runtime.client = FlakyClient()
    assert runtime.call_json(stage="test", model="fake", system="test", payload={}) == {}
    assert runtime.limiter.limit == 1
    assert service.repository.usage_summary(job_id)["retries"] == 1
    assert any(event["payload"].get("code") == "rate_limited" for event in events)

    limiter = AdaptiveLimiter(1, 2)
    for _ in range(20):
        limiter.success()
    assert limiter.limit == 2


def test_malformed_response_retry_keeps_both_usage_records(workspace, tmp_path: Path):
    source = tmp_path / "malformed.txt"
    source.write_text("A paragraph.", encoding="utf-8")
    config = fake_config()
    config.max_retries = 1
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), config)["job_id"]
    service.control_job(job_id, "run")
    runtime = LLMRuntime(
        service.repository,
        job_id,
        config,
        WorkerEventEmitter(service.repository),
    )

    class MalformedClient:
        calls = 0

        def complete(self, **kwargs):
            del kwargs
            self.calls += 1
            content = "not-json" if self.calls == 1 else "{}"
            return ModelResponse(content, ModelUsage(prompt_tokens=7, completion_tokens=2))

    runtime.client = MalformedClient()
    assert runtime.call_json(stage="test", model="fake", system="test", payload={}) == {}
    usage = service.repository.usage_summary(job_id)
    assert usage["total"]["calls"] == 2
    assert usage["total"]["prompt_tokens"] == 14
    assert usage["retry_usage"]["calls"] == 1
    with workspace.session() as connection:
        rows = connection.execute(
            "SELECT status,prompt_tokens,currency FROM llm_requests WHERE job_id=? ORDER BY attempt",
            (job_id,),
        ).fetchall()
    assert [row["status"] for row in rows] == ["failed", "succeeded"]
    assert rows[0]["prompt_tokens"] == 7
    assert rows[0]["currency"] == "USD"


def test_chapters_may_finish_out_of_order_but_storage_order_stays_stable(
    workspace, tmp_path: Path, monkeypatch
):
    source = tmp_path / "out-of-order.md"
    source.write_text(
        "# Slow\n\nThe first chapter must remain first.\n\n# Fast\n\nThe second chapter remains second.",
        encoding="utf-8",
    )
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]

    class OutOfOrderClient(FakeClient):
        completed = []

        def complete(self, **kwargs):
            payload = json.loads(kwargs["user"])
            if "segments" in payload:
                first = payload["segments"][0]["text"]
                if "Slow" in first:
                    time.sleep(0.08)
                self.completed.append(first)
            return super().complete(**kwargs)

    monkeypatch.setattr("foliocross.worker.engine.FakeClient", OutOfOrderClient)
    WorkerEngine(workspace).run(job_id, export_when_done=False)
    assert "Fast" in OutOfOrderClient.completed[0]
    chapters = service.repository.chapters_for_job(job_id)
    assert [chapter["title"] for chapter in chapters] == ["Slow", "Fast"]
    ordered_source = [
        segment["source_text"]
        for chapter in chapters
        for segment in service.repository.segments_for_chapter(chapter["id"])
    ]
    assert ordered_source[0] == "# Slow"
    assert ordered_source[-1] == "The second chapter remains second."
