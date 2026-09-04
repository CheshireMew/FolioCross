from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from foliocross.application.migration import (
    discover_wenyi_states,
    map_wenyi_segments,
    migrate_wenyi_state,
)
from foliocross.application.service import FolioCrossService


def test_copy_only_wenyi_migration(workspace, tmp_path: Path):
    source = tmp_path / "legacy.txt"
    source.write_text("Legacy paragraph.", encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    root = tmp_path / "wenyi"
    state = root / "state" / "legacy"
    (state / "chapters").mkdir(parents=True)
    manifest = {
        "title": "Legacy",
        "fmt": "text",
        "source_sha256": source_hash,
        "source_lang": "en",
        "target_lang": "zh",
        "chapters": [{"index": 0, "title": "Legacy", "status": "done"}],
    }
    (state / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (state / "chapters" / "ch0.json").write_text(
        json.dumps(
            {
                "index": 0,
                "title": "Legacy",
                "segments": [
                    {
                        "index": 0,
                        "source": "Legacy paragraph.",
                        "target_before_polish": "旧初译。",
                        "target": "旧定稿。",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    connection = sqlite3.connect(state / "glossary.db")
    connection.execute(
        "CREATE TABLE glossary(source TEXT PRIMARY KEY,target TEXT,reading TEXT,type TEXT)"
    )
    connection.execute("INSERT INTO glossary VALUES ('Legacy','旧作','','work')")
    connection.execute(
        """CREATE TABLE term_conflicts(
            id INTEGER PRIMARY KEY,source TEXT,existing_target TEXT,proposed_target TEXT,
            chapter INTEGER,note TEXT,resolved INTEGER,created_at REAL
        )"""
    )
    connection.execute("INSERT INTO term_conflicts VALUES (1,'Legacy','旧作','遗产',0,NULL,0,1.0)")
    connection.commit()
    connection.close()
    (state / "usage.json").write_text(
        json.dumps(
            {"totals": {"prompt_tokens": 100, "completion_tokens": 50, "cache_hit_tokens": 10}}
        ),
        encoding="utf-8",
    )
    (state / "analysis.json").write_text(
        json.dumps({"overview": "Legacy overview", "style": "Direct"}), encoding="utf-8"
    )
    legacy_output = tmp_path / "output" / "legacy.zh.txt"
    legacy_output.parent.mkdir()
    legacy_output.write_text("旧定稿。", encoding="utf-8")
    before = {path: path.read_bytes() for path in state.rglob("*") if path.is_file()}
    assert discover_wenyi_states(str(root))[0]["title"] == "Legacy"
    service = FolioCrossService(workspace)
    result = migrate_wenyi_state(service, state_dir=str(state), source_path=str(source))
    assert result["translated_segments"] == 1
    assert result["glossary_terms"] == 1
    assert result["glossary_conflicts"] == 1
    assert len(result["legacy_outputs"]) == 1
    assert Path(result["legacy_outputs"][0]["copied_to"]).read_text(encoding="utf-8") == "旧定稿。"
    assert result["book_context_imported"] is True
    assert result["mapping_problems"] == []
    chapter = service.repository.chapters_for_job(result["job_id"])[0]
    segment = service.repository.segments_for_chapter(chapter["id"])[0]
    assert segment["target_text"] == "旧定稿。"
    assert len(service.repository.segment_revisions(segment["id"])) == 2
    job = service.repository.get_job(result["job_id"])
    assert job["book_context"]["overview"] == "Legacy overview"
    assert job["glossary_snapshot_version"] == 1
    glossary = service.repository.list_glossary(result["job_id"])[0]
    assert glossary["target"] == "旧作"
    assert glossary["status"] == "conflict"
    assert glossary["alternatives"] == ["遗产"]
    assert any(
        artifact["kind"] == "migration_report"
        for artifact in service.repository.list_artifacts(result["job_id"])
    )
    after = {path: path.read_bytes() for path in state.rglob("*") if path.is_file()}
    assert before == after
    assert legacy_output.read_text(encoding="utf-8") == "旧定稿。"


def test_wenyi_mapping_combines_continuations_across_logical_chapters(tmp_path: Path):
    state = tmp_path / "state"
    (state / "chapters").mkdir(parents=True)
    manifest = {
        "chapters": [
            {"index": 0, "href": "part.xhtml"},
            {"index": 1, "href": "part.xhtml"},
        ]
    }
    (state / "chapters" / "ch0.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "source": "A long ",
                        "target": "一段",
                        "resource_href": "part.xhtml",
                        "cont": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (state / "chapters" / "ch1.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "source": "paragraph.",
                        "target": "长文。",
                        "resource_href": "part.xhtml",
                        "cont": True,
                    },
                    {
                        "source": "Next.",
                        "target": "下一段。",
                        "resource_href": "part.xhtml",
                        "cont": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    current = [
        {
            "id": "one",
            "source_text": "A long paragraph.",
            "locator": {"resource": "OEBPS/part.xhtml"},
        },
        {
            "id": "two",
            "source_text": "Next.",
            "locator": {"resource": "OEBPS/part.xhtml"},
        },
    ]
    mappings, problems = map_wenyi_segments(state, manifest, current)
    assert problems == []
    assert [len(old) for _, old in mappings] == [2, 1]
    assert "".join(row["target"] for row in mappings[0][1]) == "一段长文。"


def test_unsupported_wenyi_task_is_reported_and_skipped(workspace, tmp_path: Path):
    source = tmp_path / "subtitle.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello", encoding="utf-8")
    state = tmp_path / "wenyi" / "state" / "subtitle"
    state.mkdir(parents=True)
    manifest = {
        "title": "Subtitle",
        "fmt": "srt",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "chapters": [],
    }
    (state / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    discovered = discover_wenyi_states(str(tmp_path / "wenyi"))[0]
    assert discovered["supported"] is False

    result = migrate_wenyi_state(
        FolioCrossService(workspace), state_dir=str(state), source_path=str(source)
    )
    assert result["ok"] is True
    assert result["skipped"] is True
    assert Path(result["report_path"]).is_file()
    assert list(FolioCrossService(workspace).repository.list_jobs()) == []
