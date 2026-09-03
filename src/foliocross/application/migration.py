"""Copy-only importer for compatible Wenyi v0.5.2 task state."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from ..domain.models import JobConfig, ModelProfile
from ..errors import FolioCrossError
from ..infrastructure.formats.calibre import is_convertible
from ..infrastructure.repository import sha256_file, utc_now
from .service import FolioCrossService


def discover_wenyi_states(wenyi_root: str) -> list[dict[str, Any]]:
    root = Path(wenyi_root).resolve()
    state_root = root / "state"
    if not state_root.is_dir():
        raise FolioCrossError("wenyi_state_missing", f"找不到 Wenyi 状态目录：{state_root}")
    result = []
    for manifest_path in sorted(state_root.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        result.append(
            {
                "state_dir": str(manifest_path.parent),
                "title": manifest.get("title") or manifest_path.parent.name,
                "format": manifest.get("fmt", ""),
                "source_sha256": manifest.get("source_sha256", ""),
                "chapters": len(manifest.get("chapters") or []),
                "needs_source": True,
            }
        )
    return result


def _locked(path: Path) -> bool:
    if not path.exists() or os.name != "nt":
        return False
    import msvcrt

    stream = path.open("r+b")
    try:
        stream.seek(0)
        if stream.read(1) == b"":
            return False
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return False
    finally:
        stream.close()


def migrate_wenyi_state(
    service: FolioCrossService,
    *,
    state_dir: str,
    source_path: str,
) -> dict[str, Any]:
    source = Path(source_path).resolve()
    old_state = Path(state_dir).resolve()
    manifest_path = old_state / "manifest.json"
    if not manifest_path.is_file():
        raise FolioCrossError("wenyi_manifest_missing", f"找不到 Wenyi manifest：{manifest_path}")
    if _locked(old_state / ".run.lock"):
        raise FolioCrossError(
            "wenyi_task_running", "Wenyi 任务仍在运行。请先安全暂停，再执行只读导入。"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_hash = str(manifest.get("source_sha256", ""))
    actual_hash = sha256_file(source)
    if expected_hash != actual_hash:
        raise FolioCrossError(
            "wenyi_source_mismatch",
            "选择的源书与该 Wenyi 状态不匹配。",
            details={"expected_sha256": expected_hash, "actual_sha256": actual_hash},
        )
    if source.suffix.lower() in {".pdf", ".srt"} or manifest.get("fmt") in {"pdf", "srt"}:
        raise FolioCrossError("wenyi_format_unsupported", "FolioCross 首版不迁移 PDF 或 SRT 任务。")
    if service.repository.find_book_by_hash(actual_hash):
        raise FolioCrossError(
            "book_already_imported",
            "这本书已经在 FolioCross 中。为避免覆盖现有版本，没有重复导入 Wenyi 状态。",
        )

    working_override = None
    if is_convertible(str(source)):
        converted = old_state / "source" / actual_hash / "converted.epub"
        if not converted.is_file():
            raise FolioCrossError(
                "wenyi_converted_source_missing",
                "该任务缺少 Wenyi 转换后的 EPUB 缓存，无法无损迁移。",
            )
        working_override = str(converted)

    profile = ModelProfile()
    config = JobConfig(
        source_lang=str(manifest.get("source_lang", "auto")),
        target_lang="zh-CN",
        profile=profile,
    )
    imported = service.import_book(str(source), config, working_source_override=working_override)
    job_id = imported["job_id"]
    chapters = service.repository.chapters_for_job(job_id)
    translated = 0
    before_polish = 0
    for old_entry, new_chapter in zip(manifest.get("chapters") or [], chapters):
        chapter_path = old_state / "chapters" / f"ch{int(old_entry.get('index', 0))}.json"
        if not chapter_path.is_file():
            continue
        old_chapter = json.loads(chapter_path.read_text(encoding="utf-8"))
        new_segments = service.repository.segments_for_chapter(new_chapter["id"])
        old_segments = [
            item for item in old_chapter.get("segments", []) if str(item.get("source", "")).strip()
        ]
        if len(old_segments) != len(new_segments):
            service.repository.create_issue(
                job_id,
                segment_id=None,
                category="migration",
                severity="warning",
                message=f"章节“{new_chapter['title']}”的段落数量不同，未自动映射正文。",
                evidence={"wenyi": len(old_segments), "foliocross": len(new_segments)},
            )
            continue
        for old_segment, new_segment in zip(old_segments, new_segments):
            base = old_segment.get("target_before_polish")
            target = old_segment.get("target")
            if isinstance(base, str) and base.strip():
                service.repository.save_segment_revision(
                    new_segment["id"], base, origin="wenyi_translation", model="legacy"
                )
                before_polish += 1
            if isinstance(target, str) and target.strip() and target != base:
                service.repository.save_segment_revision(
                    new_segment["id"], target, origin="wenyi_final", model="legacy"
                )
                translated += 1
            elif isinstance(base, str) and base.strip():
                translated += 1

    glossary_path = old_state / "glossary.db"
    glossary_count = 0
    if glossary_path.is_file():
        connection = sqlite3.connect(f"file:{glossary_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT * FROM glossary").fetchall()
            terms = []
            for row in rows:
                item = dict(row)
                terms.append(
                    {
                        "source": item.get("source", ""),
                        "target": item.get("target", ""),
                        "type": item.get("type", "term"),
                        "reading": item.get("reading", ""),
                        "confidence": item.get("confidence", 0.5) or 0.5,
                    }
                )
            service.repository.upsert_glossary_terms(job_id, terms)
            glossary_count = len(terms)
        finally:
            connection.close()

    usage_path = old_state / "usage.json"
    usage = {}
    if usage_path.is_file():
        usage = json.loads(usage_path.read_text(encoding="utf-8"))
        totals = usage.get("totals") or usage.get("total") or usage
        prompt_tokens = int(totals.get("prompt_tokens", 0) or 0)
        completion_tokens = int(totals.get("completion_tokens", 0) or 0)
        cache_hit_tokens = int(totals.get("cache_hit_tokens", 0) or 0)
        if prompt_tokens or completion_tokens:
            request_id = service.repository.start_request(
                job_id,
                stage="wenyi_import",
                model="legacy-aggregate",
                input_hash=actual_hash,
                chapter_id=None,
                attempt=1,
            )
            service.repository.finish_request(
                request_id,
                status="succeeded",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_hit_tokens=cache_hit_tokens,
                cost=None,
            )

    service.repository.update_job(
        job_id, status="paused", stage="migrated", message="Wenyi 状态已只读导入，请检查后恢复"
    )
    report = {
        "ok": True,
        "migrated_at": utc_now(),
        "wenyi_state": str(old_state),
        "wenyi_manifest_sha256": sha256_file(manifest_path),
        "source_sha256": actual_hash,
        "book_id": imported["book_id"],
        "job_id": job_id,
        "translated_segments": translated,
        "pre_polish_revisions": before_polish,
        "glossary_terms": glossary_count,
        "legacy_usage_present": bool(usage),
        "source_modified": False,
    }
    report_path = service.workspace.imports_dir / f"wenyi-{job_id}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
