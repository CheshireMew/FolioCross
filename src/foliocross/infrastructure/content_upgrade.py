"""Add previously omitted HTML prose without replacing existing segment identities."""

import zipfile
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from bs4 import BeautifulSoup

from ..domain.models import ChapterDraft, ParsedBook
from ..errors import FolioCrossError
from .formats.common import split_long_segments
from .formats.htmlish import content_blocks
from .formats.markers import serialize_block
from .formats.registry import parse_book
from .repository import json_text, new_id, utc_now


def ensure_html_coverage(repository, job_id: str) -> int:
    job = repository.get_job(job_id)
    book = repository.get_book(job["book_id"])
    source = Path(book["working_source_path"])
    if source.suffix.lower() not in {".html", ".htm", ".epub"}:
        return 0
    if book["metadata"].get("extraction_version", 1) >= 2:
        return 0
    with repository.workspace.transaction(immediate=True) as connection:
        # Another process may have upgraded while this caller waited.
        book = repository.get_book(book["id"])
        if book["metadata"].get("extraction_version", 1) >= 2:
            return 0
        parsed = parse_book(str(source), job["config"].get("source_lang", "auto"))
        previous = {ch["locator"]["resource"]: ch for ch in repository.chapters_for_job(job_id)}
        plans = []
        added = 0
        for chapter in parsed.chapters:
            resource = chapter.locator["resource"]
            old_chapter = previous.pop(resource, None)
            old_groups = defaultdict(list)
            if old_chapter:
                for segment in repository.segments_for_chapter(old_chapter["id"]):
                    old_groups[segment["locator"]["ordinal"]].append(segment)
            remaining = iter(sorted(old_groups.items()))
            current = next(remaining, None)
            if source.suffix.lower() == ".epub":
                with zipfile.ZipFile(source) as archive:
                    soup = BeautifulSoup(archive.read(resource), "lxml-xml")
            else:
                soup = BeautifulSoup(source.read_bytes(), "lxml")
            blocks = content_blocks(soup)
            rows = []
            for draft in chapter.segments:
                ordinal = draft.locator["ordinal"]
                matched = False
                if current:
                    old_ordinal, parts = current
                    parts.sort(key=lambda item: item["locator"].get("logical_part", 0))
                    identity = parts[0]["locator"].get(
                        "marker_identity", f"{resource}:{old_ordinal}"
                    )
                    fresh, _ = serialize_block(blocks[ordinal], identity=identity)
                    if draft.locator["tag"] == parts[0]["locator"].get("tag") and fresh == "".join(
                        item["source_text"] for item in parts
                    ):
                        for part in parts:
                            part["locator"].update(
                                ordinal=ordinal, extraction_version=2, marker_identity=identity
                            )
                            rows.append(part)
                        current = next(remaining, None)
                        matched = True
                if not matched:
                    singleton = ParsedBook(
                        parsed.title,
                        parsed.author,
                        parsed.source_format,
                        parsed.source_lang,
                        [ChapterDraft(chapter.title, [draft])],
                    )
                    chunks = split_long_segments(
                        singleton, job["config"].get("max_chars_per_segment", 4000)
                    )
                    rows.extend(asdict(segment) for segment in chunks.chapters[0].segments)
                    added += len(chunks.chapters[0].segments)
            if current:
                raise FolioCrossError(
                    "source_changed", "旧段落无法与源书精确对应，已停止正文升级并保留已有译文。"
                )
            plans.append((old_chapter, chapter, rows))
        if previous:
            raise FolioCrossError("source_changed", "源书缺少已导入章节，已停止正文升级。")
        now = utc_now()
        connection.execute(
            "UPDATE chapters SET chapter_index=-chapter_index-1 WHERE book_id=?", (book["id"],)
        )
        for chapter_index, (old_chapter, chapter, rows) in enumerate(plans):
            chapter_id = old_chapter["id"] if old_chapter else new_id()
            if old_chapter:
                connection.execute(
                    "UPDATE chapters SET chapter_index=? WHERE id=?", (chapter_index, chapter_id)
                )
                connection.execute(
                    "UPDATE segments SET segment_index=-segment_index-1 WHERE chapter_id=?",
                    (chapter_id,),
                )
            else:
                connection.execute(
                    "INSERT INTO chapters(id,book_id,chapter_index,title,locator_json) VALUES (?,?,?,?,?)",
                    (
                        chapter_id,
                        book["id"],
                        chapter_index,
                        chapter.title,
                        json_text(chapter.locator),
                    ),
                )
            for index, row in enumerate(rows):
                if row.get("id"):
                    connection.execute(
                        "UPDATE segments SET segment_index=?,locator_json=? WHERE id=?",
                        (index, json_text(row["locator"]), row["id"]),
                    )
                else:
                    connection.execute(
                        "INSERT INTO segments(id,chapter_id,segment_index,source_text,locator_json,markers_json,updated_at) VALUES (?,?,?,?,?,?,?)",
                        (
                            new_id(),
                            chapter_id,
                            index,
                            row["source_text"],
                            json_text(row["locator"]),
                            json_text(row["markers"]),
                            now,
                        ),
                    )
        book["metadata"]["extraction_version"] = 2
        if book["metadata"].get("template_path"):
            book["metadata"]["template_path"] = repository.workspace.store_path(
                book["metadata"]["template_path"]
            )
        connection.execute(
            "UPDATE books SET metadata_json=?,updated_at=? WHERE id=?",
            (json_text(book["metadata"]), now, book["id"]),
        )
        connection.execute(
            "UPDATE jobs SET total_segments=(SELECT COUNT(*) FROM segments s JOIN chapters c ON c.id=s.chapter_id WHERE c.book_id=jobs.book_id),updated_at=? WHERE book_id=?",
            (now, book["id"]),
        )
        if added:
            connection.execute(
                "UPDATE jobs SET status='paused',stage='imported',current_message=? WHERE book_id=?",
                (f"正文升级补入 {added} 个待翻译段落，已有译文和人工锁定保持不变。", book["id"]),
            )
            connection.execute(
                "UPDATE job_steps SET status='pending',total=(SELECT total_segments FROM jobs WHERE id=job_id) WHERE job_id IN (SELECT id FROM jobs WHERE book_id=?) AND name IN ('translate','quality','export')",
                (book["id"],),
            )
        repository._insert_event(
            connection, job_id, "book.coverage_updated", {"added_segments": added}
        )
        return added
