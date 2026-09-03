from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from foliocross.application.migration import discover_wenyi_states, migrate_wenyi_state
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
    connection.commit()
    connection.close()
    (state / "usage.json").write_text(
        json.dumps(
            {"totals": {"prompt_tokens": 100, "completion_tokens": 50, "cache_hit_tokens": 10}}
        ),
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in state.rglob("*") if path.is_file()}
    assert discover_wenyi_states(str(root))[0]["title"] == "Legacy"
    service = FolioCrossService(workspace)
    result = migrate_wenyi_state(service, state_dir=str(state), source_path=str(source))
    assert result["translated_segments"] == 1
    assert result["glossary_terms"] == 1
    chapter = service.repository.chapters_for_job(result["job_id"])[0]
    segment = service.repository.segments_for_chapter(chapter["id"])[0]
    assert segment["target_text"] == "旧定稿。"
    assert len(service.repository.segment_revisions(segment["id"])) == 2
    after = {path: path.read_bytes() for path in state.rglob("*") if path.is_file()}
    assert before == after
