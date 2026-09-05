"""Copy-only importer for compatible Wenyi v0.5.2 task state."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

from ..domain.models import JobConfig, ModelProfile
from ..errors import FolioCrossError
from ..infrastructure.formats.conversion import is_kindle_format
from ..infrastructure.formats.markers import MARKER_PATTERN
from ..infrastructure.repository import sha256_file, utc_now
from .migration_structure import restore_wenyi_structure
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
                "supported": str(manifest.get("fmt", "")).lower() not in {"pdf", "srt"},
                "skip_reason": (
                    "FolioCross 首版不迁移 PDF 或 SRT 任务"
                    if str(manifest.get("fmt", "")).lower() in {"pdf", "srt"}
                    else ""
                ),
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


def _normalized_source(text: str) -> str:
    visible = MARKER_PATTERN.sub("", str(text)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", visible).strip()


def _resource_name(value: str) -> str:
    return PurePosixPath(str(value).replace("\\", "/")).name


def _legacy_segments(old_state: Path, manifest: dict[str, Any]) -> dict[str, list[dict]]:
    by_resource: dict[str, list[dict]] = {}
    for chapter_entry in manifest.get("chapters") or []:
        index = int(chapter_entry.get("index", 0))
        chapter_path = old_state / "chapters" / f"ch{index}.json"
        if not chapter_path.is_file():
            continue
        chapter = json.loads(chapter_path.read_text(encoding="utf-8"))
        for segment in chapter.get("segments") or []:
            source = _normalized_source(segment.get("source", ""))
            if not source:
                continue
            resource = _resource_name(
                segment.get("resource_href") or chapter_entry.get("href") or ""
            )
            by_resource.setdefault(resource, []).append({**segment, "normalized_source": source})
    return by_resource


def map_wenyi_segments(
    old_state: Path, manifest: dict[str, Any], new_segments: list[dict[str, Any]]
) -> tuple[list[tuple[dict[str, Any], list[dict[str, Any]]]], list[dict[str, Any]]]:
    """Align Wenyi split segments to current template blocks by resource and source stream."""

    legacy = _legacy_segments(old_state, manifest)
    cursors = {resource: 0 for resource in legacy}
    mappings: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    problems: list[dict[str, Any]] = []
    for segment in new_segments:
        resource = _resource_name(segment.get("locator", {}).get("resource", ""))
        target_source = _normalized_source(segment.get("source_text", ""))
        legacy_resource = resource
        if legacy_resource not in legacy and "" in legacy:
            legacy_resource = ""
        old_rows = legacy.get(legacy_resource, [])
        start = cursors.get(legacy_resource, 0)
        matched: list[dict[str, Any]] | None = None
        # Wenyi may have split a long template block into several continuation
        # segments. Its writer concatenates those pieces without a separator.
        for end in range(start, min(len(old_rows), start + 100)):
            source_parts = [row["normalized_source"] for row in old_rows[start : end + 1]]
            candidates = {"".join(source_parts), " ".join(source_parts)}
            if target_source in candidates:
                matched = old_rows[start : end + 1]
                cursors[legacy_resource] = end + 1
                break
            if min(len(candidate) for candidate in candidates) > len(target_source):
                break
        if matched is None:
            problems.append(
                {
                    "kind": "unmatched_current_segment",
                    "resource": resource,
                    "source": target_source[:240],
                    "legacy_cursor": start,
                }
            )
            continue
        mappings.append((segment, matched))

    for resource, rows in legacy.items():
        cursor = cursors.get(resource, 0)
        if cursor < len(rows):
            problems.append(
                {
                    "kind": "unconsumed_legacy_segments",
                    "resource": resource,
                    "count": len(rows) - cursor,
                    "first_source": rows[cursor]["normalized_source"][:240],
                }
            )
    return mappings, problems


def _copy_legacy_outputs(
    service: FolioCrossService, source: Path, book_id: str, job_id: str
) -> list[dict[str, str]]:
    output_dir = source.parent / "output"
    if not output_dir.is_dir():
        return []
    prefix = f"{source.stem}.zh".casefold()
    supported = {".epub", ".docx", ".html", ".htm", ".txt", ".md", ".markdown"}
    copied: list[dict[str, str]] = []
    destination_dir = service.workspace.book_export_dir(book_id) / "wenyi-import"
    for candidate in sorted(output_dir.iterdir(), key=lambda item: item.name.casefold()):
        if (
            not candidate.is_file()
            or candidate.suffix.casefold() not in supported
            or not candidate.stem.casefold().startswith(prefix)
        ):
            continue
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / candidate.name
        if destination.is_file() and sha256_file(destination) != sha256_file(candidate):
            destination = destination.with_name(
                f"{destination.stem}-{sha256_file(candidate)[:8]}{destination.suffix}"
            )
        if not destination.is_file():
            shutil.copy2(candidate, destination)
        service.repository.add_artifact(
            job_id,
            kind="translation",
            format_name=destination.suffix.lstrip("."),
            path=str(destination),
            metadata={"source": "wenyi-v0.5.2", "legacy_path": str(candidate)},
        )
        copied.append({"source": str(candidate), "copied_to": str(destination)})
    return copied


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
    manifest_format = str(manifest.get("fmt", "")).lower()
    if source.suffix.lower() in {".pdf", ".srt"} or manifest_format in {"pdf", "srt"}:
        report = {
            "ok": True,
            "skipped": True,
            "reason_code": "wenyi_format_unsupported",
            "message": "FolioCross 首版不迁移 PDF 或 SRT 任务。",
            "wenyi_state": str(old_state),
            "source_sha256": actual_hash,
            "source_modified": False,
            "migrated_at": utc_now(),
        }
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", old_state.name)[:80] or "task"
        report_path = service.workspace.imports_dir / f"wenyi-skipped-{safe_name}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report
    if service.repository.find_book_by_hash(actual_hash):
        raise FolioCrossError(
            "book_already_imported",
            "这本书已经在 FolioCross 中。为避免覆盖现有版本，没有重复导入 Wenyi 状态。",
        )

    working_override = None
    if is_kindle_format(str(source)):
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
        # Preserve the original template block boundaries. Wenyi continuation
        # segments are combined by the source-stream mapper below.
        max_chars_per_segment=10_000_000,
        profile=profile,
    )
    imported = service.import_book(str(source), config, working_source_override=working_override)
    job_id = imported["job_id"]
    chapters = service.repository.chapters_for_job(job_id)
    new_segments = [
        segment
        for chapter in chapters
        for segment in service.repository.segments_for_chapter(chapter["id"])
    ]
    mappings, mapping_problems = map_wenyi_segments(old_state, manifest, new_segments)
    translated = 0
    before_polish = 0
    structure_review_segments = 0
    for new_segment, old_segments in mappings:
        base, base_uncertain = restore_wenyi_structure(
            new_segment, old_segments, "target_before_polish"
        )
        final, uncertain = restore_wenyi_structure(new_segment, old_segments, "target")
        if not final:
            final, uncertain = base, base_uncertain
        if final and uncertain:
            structure_review_segments += 1
            service.repository.create_issue(
                job_id,
                segment_id=new_segment["id"],
                category="migration_structure",
                severity="warning",
                message="旧译文的部分行内格式按原文位置比例恢复，请检查位置。",
                evidence={"fallback_markers": uncertain},
            )
        if base:
            service.repository.save_segment_revision(
                new_segment["id"], base, origin="wenyi_translation", model="legacy"
            )
            before_polish += 1
        if final and final != base:
            service.repository.save_segment_revision(
                new_segment["id"], final, origin="wenyi_final", model="legacy"
            )
        if final:
            translated += 1

    for problem in mapping_problems:
        service.repository.create_issue(
            job_id,
            segment_id=None,
            category="migration",
            severity="warning",
            message="Wenyi 正文有一处无法根据资源和原文连续流自动映射。",
            evidence=problem,
        )

    glossary_path = old_state / "glossary.db"
    glossary_count = 0
    glossary_conflicts = 0
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
                        "first_chapter": item.get("first_chapter", 0) or 0,
                    }
                )
            service.repository.upsert_glossary_terms(job_id, terms)
            glossary_count = len(terms)
            conflict_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='term_conflicts'"
            ).fetchone()
            if conflict_table:
                conflicts = connection.execute(
                    """SELECT source,proposed_target,chapter FROM term_conflicts
                    WHERE COALESCE(resolved,0)=0 ORDER BY id"""
                ).fetchall()
                for conflict in conflicts:
                    if service.repository.record_glossary_conflict(
                        job_id,
                        str(conflict["source"]),
                        str(conflict["proposed_target"] or ""),
                        chapter_index=int(conflict["chapter"] or 0),
                    ):
                        glossary_conflicts += 1
        finally:
            connection.close()

    analysis_path = old_state / "analysis.json"
    analysis: dict[str, Any] = {}
    if analysis_path.is_file():
        loaded_analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        if isinstance(loaded_analysis, dict):
            analysis = loaded_analysis
            service.repository.update_book_context(job_id, analysis)
            for chapter in chapters:
                service.repository.update_chapter_summary(
                    chapter["id"], "从 Wenyi v0.5.2 状态导入；旧状态未单独保存本章梗概。"
                )
    if glossary_count:
        service.repository.freeze_glossary(job_id)

    service.repository.update_step(
        job_id,
        "prepare",
        status="done",
        completed=len(chapters),
        total=len(chapters),
        message="全书理解和冻结术语已从 Wenyi 导入",
    )
    service.repository.update_step(
        job_id,
        "translate",
        status="done",
        completed=translated,
        total=len(new_segments),
        message="Wenyi 译文已完成映射",
    )

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
    legacy_outputs = _copy_legacy_outputs(service, source, imported["book_id"], job_id)
    source_hash_after = sha256_file(source)
    if source_hash_after != actual_hash:
        raise FolioCrossError(
            "wenyi_source_modified",
            "迁移后源文件校验值发生变化，已停止并保留迁移报告所需状态。",
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
        "mapped_segments": len(mappings),
        "mapping_problems": mapping_problems,
        "pre_polish_revisions": before_polish,
        "structure_review_segments": structure_review_segments,
        "glossary_terms": glossary_count,
        "glossary_conflicts": glossary_conflicts,
        "book_context_imported": bool(analysis),
        "legacy_usage_present": bool(usage),
        "legacy_outputs": legacy_outputs,
        "source_modified": source_hash_after != actual_hash,
    }
    report_path = service.workspace.imports_dir / f"wenyi-{job_id}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    service.repository.add_artifact(
        job_id,
        kind="migration_report",
        format_name="json",
        path=str(report_path),
        metadata={"source": "wenyi-v0.5.2", "read_only": True},
    )
    return report
