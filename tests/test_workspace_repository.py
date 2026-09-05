from __future__ import annotations

from pathlib import Path

import pytest

from foliocross.application.service import FolioCrossService
from foliocross.domain.models import JobConfig, ModelProfile
from foliocross.errors import FolioCrossError
from foliocross.infrastructure.repository import Repository


def fake_config(output: str = "txt") -> JobConfig:
    return JobConfig(
        output_format=output,
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
        ),
    )


def test_workspace_schema_and_wal(workspace):
    assert workspace.db_path.is_file()
    with workspace.connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert versions == [1, 2, 3, 4, 5]


def test_import_creates_uuid_book_job_and_segments(workspace, tmp_path: Path):
    source = tmp_path / "story.txt"
    source.write_text(
        "Chapter 1\n\nA complete first paragraph.\n\nA complete second paragraph.", encoding="utf-8"
    )
    result = FolioCrossService(workspace).import_book(str(source), fake_config())
    repository = Repository(workspace)
    job = repository.get_job(result["job_id"])
    assert job["title"] == "Chapter 1"
    assert job["status"] == "paused"
    assert job["total_segments"] == 3
    assert job["source_characters"] == len(
        "Chapter 1A complete first paragraph.A complete second paragraph."
    )
    assert Path(job["stored_source_path"]).is_file()
    assert result["book_id"] != result["job_id"]


def test_same_source_reopens_the_existing_content_addressed_job(workspace, tmp_path: Path):
    source = tmp_path / "same.txt"
    source.write_text("A book paragraph.", encoding="utf-8")
    service = FolioCrossService(workspace)
    one = service.import_book(str(source), fake_config())
    two = service.import_book(str(source), fake_config())
    assert one["book_id"] == two["book_id"]
    assert one["job_id"] == two["job_id"]
    assert two["reused"] is True


def test_same_title_and_replaced_source_path_create_distinct_books(workspace, tmp_path: Path):
    source = tmp_path / "same-title.txt"
    service = FolioCrossService(workspace)
    source.write_text("First edition.", encoding="utf-8")
    first = service.import_book(str(source), fake_config())
    source.write_text("Second edition with different content.", encoding="utf-8")
    second = service.import_book(str(source), fake_config())
    assert first["book_id"] != second["book_id"]
    assert first["job_id"] != second["job_id"]
    assert (
        Path(service.repository.get_job(first["job_id"])["stored_source_path"]).read_text(
            encoding="utf-8"
        )
        == "First edition."
    )


def test_manual_revision_locks_segment_and_uses_optimistic_version(workspace, tmp_path: Path):
    source = tmp_path / "edit.txt"
    source.write_text("Text to edit.", encoding="utf-8")
    service = FolioCrossService(workspace)
    imported = service.import_book(str(source), fake_config())
    chapter = service.repository.chapters_for_job(imported["job_id"])[0]
    segment = service.repository.segments_for_chapter(chapter["id"])[0]
    result = service.edit_segment(segment["id"], "人工译文", expected_version=0)
    assert result["version"] == 1
    stored = service.repository.segment(segment["id"])
    assert stored["locked"] is True
    with pytest.raises(FolioCrossError, match="已被其他操作修改"):
        service.edit_segment(segment["id"], "过期修改", expected_version=0)
    with pytest.raises(FolioCrossError, match="不会被自动操作覆盖"):
        service.repository.save_segment_revision(
            segment["id"], "自动覆盖", origin="model_translation"
        )


def test_glossary_conflict_and_affected_segments(workspace, tmp_path: Path):
    source = tmp_path / "terms.txt"
    source.write_text("Alice meets Alice.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    service.repository.upsert_glossary_terms(job_id, [{"source": "Alice", "target": "爱丽丝"}])
    service.repository.upsert_glossary_terms(job_id, [{"source": "Alice", "target": "艾丽斯"}])
    term = service.repository.list_glossary(job_id)[0]
    assert term["status"] == "conflict"
    assert "艾丽斯" in term["alternatives"]
    updated = service.repository.update_glossary_term(job_id, "Alice", "爱丽丝")
    assert updated["affected_segments"] == 1
    affected = service.repository.affected_segments(job_id, "Alice")
    assert len(affected) == 1
    assert affected[0]["chapter_title"]
    assert affected[0]["source_text"] == "Alice meets Alice."


def test_glossary_choice_is_deterministic_across_concurrent_scan_order(workspace, tmp_path: Path):
    source = tmp_path / "term-ranking.txt"
    source.write_text("Alice appears here.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    service.repository.upsert_glossary_terms(
        job_id,
        [
            {
                "source": "Alice",
                "target": "艾丽斯",
                "frequency": 1,
                "confidence": 0.9,
                "chapter_index": 0,
            }
        ],
    )
    service.repository.upsert_glossary_terms(
        job_id,
        [
            {
                "source": "Alice",
                "target": "爱丽丝",
                "frequency": 4,
                "confidence": 0.7,
                "chapter_index": 2,
            }
        ],
    )
    term = service.repository.list_glossary(job_id)[0]
    assert term["target"] == "爱丽丝"
    assert term["status"] == "conflict"
    assert term["alternatives"] == ["艾丽斯"]


def test_history_restore_and_explicit_glossary_apply(workspace, tmp_path: Path):
    source = tmp_path / "history.txt"
    source.write_text("Alice writes a book.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    chapter = service.repository.chapters_for_job(job_id)[0]
    segment = service.repository.segments_for_chapter(chapter["id"])[0]
    service.edit_segment(segment["id"], "爱丽丝写了一本书。", expected_version=0)
    first_revision = service.repository.segment_revisions(segment["id"])[0]
    service.edit_segment(segment["id"], "爱丽丝正在写书。", expected_version=1)
    restored = service.restore_revision(first_revision["id"])
    assert restored["version"] == 3
    assert service.repository.segment(segment["id"])["target_text"] == "爱丽丝写了一本书。"

    service.repository.upsert_glossary_terms(job_id, [{"source": "Alice", "target": "爱丽丝"}])
    saved_only = service.update_glossary(job_id, "Alice", "艾丽斯", apply_existing=False)
    assert saved_only["applied_segments"] == 0
    assert service.repository.segment(segment["id"])["target_text"] == "爱丽丝写了一本书。"
    applied = service.update_glossary(job_id, "Alice", "艾丽斯", apply_existing=True)
    # The prior call already changed the term, so switch it back first and then explicitly apply.
    assert applied["applied_segments"] == 0
    service.update_glossary(job_id, "Alice", "爱丽丝", apply_existing=False)
    applied = service.update_glossary(job_id, "Alice", "艾丽斯", apply_existing=True)
    assert applied["applied_segments"] == 1
    assert service.repository.segment(segment["id"])["target_text"] == "艾丽斯写了一本书。"


def test_stale_running_job_is_marked_interrupted_and_can_be_archived(workspace, tmp_path: Path):
    source = tmp_path / "interrupted.txt"
    source.write_text("A resumable paragraph.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    service.repository.update_job(job_id, status="translating", stage="translate")
    recovered = service.repository.recover_interrupted_jobs()
    assert recovered == [job_id]
    job = service.repository.get_job(job_id)
    assert job["status"] == "interrupted"
    assert job["desired_state"] == "pause"
    service.archive_job(job_id)
    assert all(row["id"] != job_id for row in service.repository.list_jobs())
    assert any(row["id"] == job_id for row in service.repository.list_jobs(include_archived=True))


def test_speed_uses_active_time_and_excludes_paused_wall_clock(workspace, tmp_path: Path):
    source = tmp_path / "active-time.txt"
    source.write_text("One paragraph.\n\nAnother paragraph.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), fake_config())["job_id"]
    service.repository.update_job(job_id, status="translating", stage="translate")
    service.repository.update_job(job_id, status="paused", message="paused")
    with workspace.transaction(immediate=True) as connection:
        connection.execute(
            """UPDATE jobs SET active_elapsed_seconds=120,
            started_at='2000-01-01T00:00:00.000Z',completed_segments=1 WHERE id=?""",
            (job_id,),
        )
    job = service.repository.get_job(job_id)
    assert 119.9 <= job["elapsed_seconds"] <= 120.1
    assert job["segments_per_minute"] == 0.5


def test_model_and_job_configuration_are_persisted_as_snapshots(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    saved = service.save_model_profile(
        {
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3:8b",
            "input_price": "",
            "cached_input_price": "",
            "output_price": "",
            "currency": "USD",
            "effective_date": "",
        }
    )
    assert saved["provider"] == "ollama"
    assert saved["input_price_per_million"] is None
    assert saved["peak_multiplier"] == 1.0
    assert saved["peak_windows_utc"] == []
    assert saved["price_source"] is None
    source = tmp_path / "configured.txt"
    source.write_text("A configurable paragraph.", encoding="utf-8")
    job_id = service.import_book(str(source))["job_id"]
    service.configure_job(
        job_id,
        source_lang="en",
        output_format="docx",
        bilingual=True,
        soft_budget=0.75,
        hard_budget=1.25,
    )
    config = service.repository.get_job(job_id)["config"]
    assert config["source_lang"] == "en"
    assert config["output_format"] == "docx"
    assert config["bilingual"] is True
    assert config["soft_budget"] == 0.75
    assert config["hard_budget"] == 1.25
    assert config["profile"]["provider"] == "ollama"
