"""Transactional access to the FolioCross workspace database."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..domain.models import ChapterDraft, DesiredState, JobConfig, JobStatus, ParsedBook
from ..errors import FolioCrossError
from .pricing import estimate_book_tokens, estimate_cost
from .workspace import Workspace


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def decode_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Repository:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.workspace.initialize()

    def recover_interrupted_jobs(self) -> list[str]:
        """Mark stale running states as resumable interruptions after an unclean exit."""

        active_states = {
            JobStatus.PREPARING.value,
            JobStatus.TRANSLATING.value,
            JobStatus.QUALITY_CHECK.value,
            JobStatus.EXPORTING.value,
        }
        with self.workspace.session() as connection:
            rows = connection.execute(
                "SELECT id,status FROM jobs WHERE status IN (?,?,?,?)",
                tuple(active_states),
            ).fetchall()
        recovered = []
        for row in rows:
            if self._job_lock_is_held(row["id"]):
                continue
            now = utc_now()
            with self.workspace.transaction(immediate=True) as connection:
                changed = connection.execute(
                    """UPDATE jobs SET status=?,desired_state=?,current_message=?,updated_at=?
                    WHERE id=? AND status=?""",
                    (
                        JobStatus.INTERRUPTED.value,
                        DesiredState.PAUSE.value,
                        "上次运行意外中断，可以从已完成的批次继续",
                        now,
                        row["id"],
                        row["status"],
                    ),
                ).rowcount
                if changed:
                    self._insert_event(
                        connection,
                        row["id"],
                        "job.interrupted",
                        {"previous_status": row["status"]},
                    )
                    recovered.append(row["id"])
        return recovered

    def _job_lock_is_held(self, job_id: str) -> bool:
        path = self.workspace.jobs_dir / job_id / "worker.lock"
        if not path.is_file():
            return False
        try:
            with path.open("r+b") as stream:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError:
                        return True
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    return False
                import fcntl  # pragma: no cover

                try:  # pragma: no cover
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:  # pragma: no cover
                    return True
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)  # pragma: no cover
                return False
        except OSError:
            return True

    def create_book_and_job(
        self,
        *,
        book_id: str,
        job_id: str,
        parsed: ParsedBook,
        source_hash: str,
        original_path: str,
        stored_source_path: str,
        working_source_path: str,
        config: JobConfig,
    ) -> tuple[str, str]:
        now = utc_now()
        total_segments = sum(len(chapter.segments) for chapter in parsed.chapters)
        estimated_input, estimated_output = estimate_book_tokens(
            segment.source_text for chapter in parsed.chapters for segment in chapter.segments
        )
        estimated_cost = estimate_cost(config.profile, estimated_input, estimated_output)
        with self.workspace.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT id, stored_source_path, working_source_path FROM books WHERE sha256=?",
                (source_hash,),
            ).fetchone()
            if existing:
                book_id = existing["id"]
            else:
                connection.execute(
                    """INSERT INTO books(
                        id, sha256, title, author, source_format, source_lang, target_lang,
                        original_path, stored_source_path, working_source_path, metadata_json,
                        warnings_json, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        book_id,
                        source_hash,
                        parsed.title,
                        parsed.author,
                        parsed.source_format,
                        config.source_lang,
                        config.target_lang,
                        original_path,
                        stored_source_path,
                        working_source_path,
                        json_text(parsed.metadata),
                        json_text(parsed.warnings),
                        now,
                        now,
                    ),
                )
                self._insert_chapters(connection, book_id, parsed.chapters, now)

            connection.execute(
                """INSERT INTO jobs(
                    id, book_id, status, desired_state, stage, preset, config_json,
                    total_segments, completed_segments, estimated_input_tokens,
                    estimated_output_tokens, estimated_cost, currency, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    book_id,
                    JobStatus.PAUSED.value,
                    DesiredState.PAUSE.value,
                    "imported",
                    config.preset,
                    json_text(config.to_dict()),
                    total_segments,
                    0,
                    estimated_input,
                    estimated_output,
                    estimated_cost,
                    config.profile.currency,
                    now,
                    now,
                ),
            )
            for step in ("prepare", "translate", "quality", "export"):
                connection.execute(
                    "INSERT INTO job_steps(job_id,name,status,total) VALUES (?,?,?,?)",
                    (
                        job_id,
                        step,
                        "pending",
                        total_segments if step != "prepare" else len(parsed.chapters),
                    ),
                )
            self._insert_event(connection, job_id, "book.imported", {"book_id": book_id})
        return book_id, job_id

    @staticmethod
    def _insert_chapters(
        connection, book_id: str, chapters: Iterable[ChapterDraft], now: str
    ) -> None:
        for chapter_index, chapter in enumerate(chapters):
            chapter_id = new_id()
            connection.execute(
                "INSERT INTO chapters(id,book_id,chapter_index,title,locator_json) VALUES (?,?,?,?,?)",
                (chapter_id, book_id, chapter_index, chapter.title, json_text(chapter.locator)),
            )
            for segment_index, segment in enumerate(chapter.segments):
                connection.execute(
                    """INSERT INTO segments(
                        id,chapter_id,segment_index,source_text,locator_json,markers_json,updated_at
                    ) VALUES (?,?,?,?,?,?,?)""",
                    (
                        new_id(),
                        chapter_id,
                        segment_index,
                        segment.source_text,
                        json_text(segment.locator),
                        json_text(segment.markers),
                        now,
                    ),
                )

    def list_books(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE b.archived=0"
        with self.workspace.session() as connection:
            rows = connection.execute(
                f"""SELECT b.*,
                    (SELECT j.id FROM jobs j WHERE j.book_id=b.id ORDER BY j.created_at DESC LIMIT 1) latest_job_id,
                    (SELECT j.status FROM jobs j WHERE j.book_id=b.id ORDER BY j.created_at DESC LIMIT 1) latest_status
                    FROM books b {where} ORDER BY b.updated_at DESC"""
            ).fetchall()
        return [self._decode_book(dict(row)) for row in rows]

    def list_jobs(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE j.archived=0"
        with self.workspace.session() as connection:
            rows = connection.execute(
                f"""SELECT j.*, b.title, b.author, b.source_format,
                    (SELECT COALESCE(SUM(LENGTH(s.source_text)),0) FROM segments s
                     JOIN chapters c ON c.id=s.chapter_id WHERE c.book_id=j.book_id) source_characters
                    FROM jobs j JOIN books b ON b.id=j.book_id
                    {where} ORDER BY j.updated_at DESC"""
            ).fetchall()
        return [self._decode_job(dict(row)) for row in rows]

    def archive_job(self, job_id: str) -> None:
        with self.workspace.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE jobs SET archived=1,updated_at=? WHERE id=?", (utc_now(), job_id)
            ).rowcount
            if not changed:
                raise FolioCrossError("job_not_found", f"找不到任务：{job_id}")
            self._insert_event(connection, job_id, "job.archived", {})

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.workspace.session() as connection:
            row = connection.execute(
                """SELECT j.*, b.title, b.author, b.source_format, b.stored_source_path,
                    b.working_source_path, b.metadata_json, b.warnings_json,
                    (SELECT COALESCE(SUM(LENGTH(s.source_text)),0) FROM segments s
                     JOIN chapters c ON c.id=s.chapter_id WHERE c.book_id=j.book_id) source_characters
                    FROM jobs j JOIN books b ON b.id=j.book_id WHERE j.id=?""",
                (job_id,),
            ).fetchone()
        if not row:
            raise FolioCrossError("job_not_found", f"找不到任务：{job_id}")
        return self._decode_job(dict(row))

    def resolve_job_id(self, job_or_book_id: str) -> str:
        with self.workspace.session() as connection:
            row = connection.execute("SELECT id FROM jobs WHERE id=?", (job_or_book_id,)).fetchone()
            if not row:
                row = connection.execute(
                    "SELECT id FROM jobs WHERE book_id=? AND archived=0 ORDER BY created_at DESC LIMIT 1",
                    (job_or_book_id,),
                ).fetchone()
        if not row:
            raise FolioCrossError("job_not_found", f"找不到任务或书籍：{job_or_book_id}")
        return str(row["id"])

    def latest_job_for_book(
        self, book_id: str, *, include_archived: bool = True
    ) -> dict[str, Any] | None:
        archived = "" if include_archived else "AND j.archived=0"
        with self.workspace.session() as connection:
            row = connection.execute(
                f"""SELECT j.*,b.title,b.author,b.source_format,b.stored_source_path,
                    b.working_source_path,b.metadata_json,b.warnings_json,
                    (SELECT COALESCE(SUM(LENGTH(s.source_text)),0) FROM segments s
                     JOIN chapters c ON c.id=s.chapter_id WHERE c.book_id=j.book_id) source_characters
                    FROM jobs j JOIN books b ON b.id=j.book_id
                    WHERE j.book_id=? {archived} ORDER BY j.created_at DESC LIMIT 1""",
                (book_id,),
            ).fetchone()
        return self._decode_job(dict(row)) if row else None

    def unarchive_job(self, job_id: str) -> None:
        with self.workspace.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE jobs SET archived=0,updated_at=? WHERE id=?", (utc_now(), job_id)
            )

    def get_book(self, book_id: str) -> dict[str, Any]:
        with self.workspace.session() as connection:
            row = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not row:
            raise FolioCrossError("book_not_found", f"找不到书籍：{book_id}")
        return self._decode_book(dict(row))

    def find_book_by_hash(self, source_hash: str) -> dict[str, Any] | None:
        with self.workspace.session() as connection:
            row = connection.execute(
                "SELECT * FROM books WHERE sha256=?", (source_hash,)
            ).fetchone()
        return self._decode_book(dict(row)) if row else None

    def chapters_for_job(self, job_id: str) -> list[dict[str, Any]]:
        job = self.get_job(job_id)
        with self.workspace.session() as connection:
            rows = connection.execute(
                """SELECT c.*,
                    COUNT(s.id) segment_count,
                    SUM(CASE WHEN s.target_text<>'' THEN 1 ELSE 0 END) translated_count
                    FROM chapters c LEFT JOIN segments s ON s.chapter_id=c.id
                    WHERE c.book_id=? GROUP BY c.id ORDER BY c.chapter_index""",
                (job["book_id"],),
            ).fetchall()
        return [self._decode_chapter(dict(row)) for row in rows]

    def segments_for_chapter(self, chapter_id: str) -> list[dict[str, Any]]:
        with self.workspace.session() as connection:
            rows = connection.execute(
                "SELECT * FROM segments WHERE chapter_id=? ORDER BY segment_index", (chapter_id,)
            ).fetchall()
        return [self._decode_segment(dict(row)) for row in rows]

    def pending_chapters(self, job_id: str) -> list[dict[str, Any]]:
        return [
            chapter
            for chapter in self.chapters_for_job(job_id)
            if chapter["translated_count"] < chapter["segment_count"]
        ]

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        message: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        heartbeat: bool = False,
        finished: bool = False,
    ) -> None:
        fields = ["updated_at=?"]
        values: list[Any] = [utc_now()]
        for name, value in (
            ("status", status),
            ("stage", stage),
            ("current_message", message),
            ("error_code", error_code),
            ("error_message", error_message),
        ):
            if value is not None:
                fields.append(f"{name}=?")
                values.append(value)
        if heartbeat:
            fields.append("heartbeat_at=?")
            values.append(utc_now())
        if status in {JobStatus.PREPARING.value, JobStatus.TRANSLATING.value}:
            fields.append("started_at=COALESCE(started_at,?)")
            values.append(utc_now())
        if finished:
            fields.append("finished_at=?")
            values.append(utc_now())
        values.append(job_id)
        with self.workspace.transaction(immediate=True) as connection:
            connection.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", values)

    def update_job_config(self, job_id: str, config: JobConfig) -> None:
        with self.workspace.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT status,estimated_input_tokens,estimated_output_tokens FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row:
                raise FolioCrossError("job_not_found", f"找不到任务：{job_id}")
            if row["status"] in {
                JobStatus.PREPARING.value,
                JobStatus.TRANSLATING.value,
                JobStatus.QUALITY_CHECK.value,
                JobStatus.EXPORTING.value,
            }:
                raise FolioCrossError("job_is_running", "任务运行期间不能修改配置。")
            estimated = estimate_cost(
                config.profile,
                int(row["estimated_input_tokens"]),
                int(row["estimated_output_tokens"]),
            )
            connection.execute(
                """UPDATE jobs SET preset=?,config_json=?,estimated_cost=?,currency=?,updated_at=?
                WHERE id=?""",
                (
                    config.preset,
                    json_text(config.to_dict()),
                    estimated,
                    config.profile.currency,
                    utc_now(),
                    job_id,
                ),
            )

    def update_step(
        self,
        job_id: str,
        name: str,
        *,
        status: str,
        completed: int | None = None,
        total: int | None = None,
        message: str = "",
    ) -> None:
        fields = ["status=?", "message=?"]
        values: list[Any] = [status, message]
        if completed is not None:
            fields.append("completed=?")
            values.append(completed)
        if total is not None:
            fields.append("total=?")
            values.append(total)
        if status == "running":
            fields.append("started_at=COALESCE(started_at,?)")
            values.append(utc_now())
        if status in {"done", "failed", "skipped"}:
            fields.append("finished_at=?")
            values.append(utc_now())
        values.extend((job_id, name))
        with self.workspace.transaction(immediate=True) as connection:
            connection.execute(
                f"UPDATE job_steps SET {', '.join(fields)} WHERE job_id=? AND name=?", values
            )

    def set_desired_state(self, job_id: str, state: DesiredState | str) -> None:
        value = state.value if isinstance(state, DesiredState) else state
        with self.workspace.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE jobs SET desired_state=?,updated_at=? WHERE id=?",
                (value, utc_now(), job_id),
            ).rowcount
            if not changed:
                raise FolioCrossError("job_not_found", f"找不到任务：{job_id}")
            self._insert_event(connection, job_id, "job.control_requested", {"state": value})

    def desired_state(self, job_id: str) -> str:
        with self.workspace.session() as connection:
            row = connection.execute(
                "SELECT desired_state FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        if not row:
            raise FolioCrossError("job_not_found", f"找不到任务：{job_id}")
        return row[0]

    def save_segment_revision(
        self,
        segment_id: str,
        text: str,
        *,
        origin: str,
        model: str | None = None,
        instruction: str | None = None,
        lock: bool = False,
        expected_version: int | None = None,
        quality: dict[str, Any] | None = None,
        allow_locked: bool = False,
    ) -> int:
        with self.workspace.transaction(immediate=True) as connection:
            current = connection.execute(
                "SELECT version,locked FROM segments WHERE id=?", (segment_id,)
            ).fetchone()
            if not current:
                raise FolioCrossError("segment_not_found", f"找不到段落：{segment_id}")
            if expected_version is not None and current["version"] != expected_version:
                raise FolioCrossError(
                    "segment_version_conflict",
                    "该段落已被其他操作修改，请刷新后再保存。",
                    details={"expected": expected_version, "actual": current["version"]},
                )
            if current["locked"] and origin != "manual" and not allow_locked:
                raise FolioCrossError("segment_locked", "人工编辑的段落不会被自动操作覆盖。")
            version = int(current["version"]) + 1
            revision_id = new_id()
            now = utc_now()
            connection.execute(
                """INSERT INTO segment_revisions(
                    id,segment_id,version,text,origin,model,instruction,created_at
                ) VALUES (?,?,?,?,?,?,?,?)""",
                (revision_id, segment_id, version, text, origin, model, instruction, now),
            )
            connection.execute(
                """UPDATE segments SET target_text=?,status=?,locked=?,quality_json=?,
                    version=?,updated_at=? WHERE id=?""",
                (
                    text,
                    "translated" if not quality or not quality.get("issues") else "needs_review",
                    1 if lock or current["locked"] else 0,
                    json_text(quality or {}),
                    version,
                    now,
                    segment_id,
                ),
            )
            connection.execute(
                """UPDATE jobs SET completed_segments=(
                    SELECT COUNT(*) FROM segments s JOIN chapters c ON c.id=s.chapter_id
                    WHERE c.book_id=jobs.book_id AND s.target_text<>''
                ),updated_at=? WHERE book_id=(
                    SELECT c.book_id FROM chapters c JOIN segments s ON s.chapter_id=c.id WHERE s.id=?
                )""",
                (now, segment_id),
            )
        return version

    def segment_revisions(self, segment_id: str) -> list[dict[str, Any]]:
        with self.workspace.session() as connection:
            rows = connection.execute(
                "SELECT * FROM segment_revisions WHERE segment_id=? ORDER BY version DESC",
                (segment_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revision(self, revision_id: str) -> dict[str, Any]:
        with self.workspace.session() as connection:
            row = connection.execute(
                "SELECT * FROM segment_revisions WHERE id=?", (revision_id,)
            ).fetchone()
        if not row:
            raise FolioCrossError("revision_not_found", f"找不到历史版本：{revision_id}")
        return dict(row)

    def segment_context(self, segment_id: str) -> dict[str, Any]:
        with self.workspace.session() as connection:
            row = connection.execute(
                """SELECT s.*, c.id chapter_id, c.title chapter_title, c.summary chapter_summary,
                    c.chapter_index, j.id job_id, j.book_context_json
                    FROM segments s JOIN chapters c ON c.id=s.chapter_id
                    JOIN jobs j ON j.book_id=c.book_id WHERE s.id=?
                    ORDER BY j.created_at DESC LIMIT 1""",
                (segment_id,),
            ).fetchone()
        if not row:
            raise FolioCrossError("segment_not_found", f"找不到段落：{segment_id}")
        item = self._decode_segment(dict(row))
        item["book_context"] = decode_json(item.pop("book_context_json"), {})
        return item

    def update_chapter_summary(self, chapter_id: str, summary: str) -> None:
        with self.workspace.transaction(immediate=True) as connection:
            connection.execute("UPDATE chapters SET summary=? WHERE id=?", (summary, chapter_id))

    def update_book_context(self, job_id: str, context: dict[str, Any]) -> None:
        with self.workspace.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE jobs SET book_context_json=?,updated_at=? WHERE id=?",
                (json_text(context), utc_now(), job_id),
            )

    def upsert_glossary_terms(self, job_id: str, terms: Iterable[dict[str, Any]]) -> None:
        now = utc_now()
        with self.workspace.transaction(immediate=True) as connection:
            for item in terms:
                source = str(item.get("source", "")).strip()
                target = str(item.get("target", "")).strip()
                if not source or not target:
                    continue
                frequency = max(1, int(item.get("frequency", 1)))
                confidence = min(1.0, max(0.0, float(item.get("confidence", 0.5))))
                first_chapter = max(0, int(item.get("chapter_index", 0)))
                existing = connection.execute(
                    "SELECT * FROM glossary_terms WHERE job_id=? AND source=?", (job_id, source)
                ).fetchone()
                candidate_count = connection.execute(
                    "SELECT COUNT(*) FROM glossary_candidates WHERE job_id=? AND source=?",
                    (job_id, source),
                ).fetchone()[0]
                if existing and not candidate_count:
                    connection.execute(
                        """INSERT INTO glossary_candidates(
                            job_id,source,target,term_type,reading,frequency,confidence,first_chapter
                        ) VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            job_id,
                            source,
                            existing["target"],
                            existing["term_type"],
                            existing["reading"],
                            existing["frequency"],
                            existing["confidence"],
                            existing["first_chapter"],
                        ),
                    )
                connection.execute(
                    """INSERT INTO glossary_candidates(
                        job_id,source,target,term_type,reading,frequency,confidence,first_chapter
                    ) VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(job_id,source,target) DO UPDATE SET
                        frequency=frequency+excluded.frequency,
                        confidence=MAX(confidence,excluded.confidence),
                        first_chapter=MIN(first_chapter,excluded.first_chapter)""",
                    (
                        job_id,
                        source,
                        target,
                        str(item.get("type", "term")),
                        str(item.get("reading", "")),
                        frequency,
                        confidence,
                        first_chapter,
                    ),
                )
                candidates = connection.execute(
                    """SELECT * FROM glossary_candidates WHERE job_id=? AND source=?
                    ORDER BY frequency DESC,confidence DESC,first_chapter ASC,target ASC""",
                    (job_id, source),
                ).fetchall()
                chosen = candidates[0]
                chosen_target = (
                    existing["target"]
                    if existing and int(existing["version"]) > 1
                    else chosen["target"]
                )
                alternatives = [
                    row["target"] for row in candidates if row["target"] != chosen_target
                ]
                status = (
                    existing["status"]
                    if existing and int(existing["version"]) > 1
                    else ("conflict" if len(candidates) > 1 else "approved")
                )
                if not existing:
                    connection.execute(
                        """INSERT INTO glossary_terms(
                            id,job_id,source,target,term_type,reading,confidence,frequency,
                            first_chapter,status,alternatives_json,created_at,updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            new_id(),
                            job_id,
                            source,
                            chosen_target,
                            chosen["term_type"],
                            chosen["reading"],
                            chosen["confidence"],
                            sum(row["frequency"] for row in candidates),
                            chosen["first_chapter"],
                            status,
                            json_text(alternatives),
                            now,
                            now,
                        ),
                    )
                    continue
                connection.execute(
                    """UPDATE glossary_terms SET target=?,term_type=?,reading=?,frequency=?,
                        confidence=?,first_chapter=?,status=?,alternatives_json=?,updated_at=?
                        WHERE id=?""",
                    (
                        chosen_target,
                        chosen["term_type"],
                        chosen["reading"],
                        sum(row["frequency"] for row in candidates),
                        chosen["confidence"],
                        chosen["first_chapter"],
                        status,
                        json_text(alternatives),
                        now,
                        existing["id"],
                    ),
                )

    def list_glossary(self, job_id: str) -> list[dict[str, Any]]:
        with self.workspace.session() as connection:
            rows = connection.execute(
                "SELECT * FROM glossary_terms WHERE job_id=? ORDER BY first_chapter,source",
                (job_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["alternatives"] = decode_json(item.pop("alternatives_json"), [])
            result.append(item)
        return result

    def record_glossary_conflict(
        self,
        job_id: str,
        source: str,
        proposed_target: str,
        *,
        chapter_index: int = 0,
    ) -> bool:
        """Preserve a legacy alternative without changing the selected translation."""

        if not source.strip() or not proposed_target.strip():
            return False
        now = utc_now()
        with self.workspace.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM glossary_terms WHERE job_id=? AND source=?", (job_id, source)
            ).fetchone()
            if not row or row["target"] == proposed_target:
                return False
            alternatives = decode_json(row["alternatives_json"], [])
            if proposed_target not in alternatives:
                alternatives.append(proposed_target)
            connection.execute(
                """INSERT INTO glossary_candidates(
                    job_id,source,target,term_type,reading,frequency,confidence,first_chapter
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id,source,target) DO NOTHING""",
                (
                    job_id,
                    source,
                    proposed_target,
                    row["term_type"],
                    row["reading"],
                    1,
                    row["confidence"],
                    max(0, int(chapter_index)),
                ),
            )
            connection.execute(
                """UPDATE glossary_terms SET status='conflict',alternatives_json=?,
                    version=version+1,updated_at=? WHERE id=?""",
                (json_text(alternatives), now, row["id"]),
            )
        return True

    def freeze_glossary(self, job_id: str) -> dict[str, Any]:
        terms = self.list_glossary(job_id)
        snapshot = [
            {
                "source": term["source"],
                "target": term["target"],
                "term_type": term["term_type"],
                "status": term["status"],
                "term_version": int(term["version"]),
            }
            for term in terms
            if term["status"] != "rejected"
        ]
        now = utc_now()
        with self.workspace.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT glossary_snapshot_version FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                raise FolioCrossError("job_not_found", f"找不到任务：{job_id}")
            version = int(row["glossary_snapshot_version"]) + 1
            connection.execute(
                """UPDATE jobs SET glossary_snapshot_json=?,glossary_snapshot_version=?,
                    glossary_snapshot_at=?,updated_at=? WHERE id=?""",
                (json_text(snapshot), version, now, now, job_id),
            )
            self._insert_event(
                connection,
                job_id,
                "glossary.frozen",
                {"version": version, "terms": len(snapshot)},
            )
        return {"version": version, "terms": snapshot, "frozen_at": now}

    def glossary_snapshot(self, job_id: str) -> dict[str, Any]:
        with self.workspace.session() as connection:
            row = connection.execute(
                """SELECT glossary_snapshot_json,glossary_snapshot_version,
                    glossary_snapshot_at FROM jobs WHERE id=?""",
                (job_id,),
            ).fetchone()
        if not row:
            raise FolioCrossError("job_not_found", f"找不到任务：{job_id}")
        return {
            "version": int(row["glossary_snapshot_version"]),
            "terms": decode_json(row["glossary_snapshot_json"], []),
            "frozen_at": row["glossary_snapshot_at"],
        }

    def update_glossary_term(
        self, job_id: str, source: str, target: str, *, status: str = "approved"
    ) -> dict[str, Any]:
        if not source.strip() or not target.strip():
            raise FolioCrossError("invalid_term", "术语原文和译名都不能为空。")
        now = utc_now()
        with self.workspace.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM glossary_terms WHERE job_id=? AND source=?", (job_id, source)
            ).fetchone()
            previous_target = str(row["target"]) if row else ""
            if row:
                connection.execute(
                    "UPDATE glossary_terms SET target=?,status=?,version=version+1,updated_at=? WHERE id=?",
                    (target, status, now, row["id"]),
                )
                term_id = row["id"]
            else:
                term_id = new_id()
                connection.execute(
                    """INSERT INTO glossary_terms(
                        id,job_id,source,target,status,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?)""",
                    (term_id, job_id, source, target, status, now, now),
                )
            affected = connection.execute(
                """SELECT COUNT(*) FROM segments s JOIN chapters c ON c.id=s.chapter_id
                    JOIN jobs j ON j.book_id=c.book_id WHERE j.id=? AND instr(s.source_text,?)>0""",
                (job_id, source),
            ).fetchone()[0]
        return {
            "id": term_id,
            "source": source,
            "target": target,
            "previous_target": previous_target,
            "status": status,
            "affected_segments": int(affected),
        }

    def segments_containing_source(self, job_id: str, source: str) -> list[dict[str, Any]]:
        with self.workspace.session() as connection:
            rows = connection.execute(
                """SELECT s.* FROM segments s JOIN chapters c ON c.id=s.chapter_id
                    JOIN jobs j ON j.book_id=c.book_id
                    WHERE j.id=? AND instr(s.source_text,?)>0 AND s.target_text<>''
                    ORDER BY c.chapter_index,s.segment_index""",
                (job_id, source),
            ).fetchall()
        return [self._decode_segment(dict(row)) for row in rows]

    def affected_segments(self, job_id: str, source: str) -> list[dict[str, Any]]:
        with self.workspace.session() as connection:
            rows = connection.execute(
                """SELECT s.*,c.chapter_index,c.title chapter_title
                    FROM segments s JOIN chapters c ON c.id=s.chapter_id
                    JOIN jobs j ON j.book_id=c.book_id
                    WHERE j.id=? AND instr(s.source_text,?)>0
                    ORDER BY c.chapter_index,s.segment_index""",
                (job_id, source),
            ).fetchall()
        return [self._decode_segment(dict(row)) for row in rows]

    def relevant_glossary(
        self, job_id: str, text: str, *, frozen: bool = True
    ) -> list[dict[str, Any]]:
        snapshot = self.glossary_snapshot(job_id) if frozen else {"version": 0, "terms": []}
        terms = snapshot["terms"] if snapshot["version"] else self.list_glossary(job_id)
        return [term for term in terms if term["source"] in text]

    def create_issue(
        self,
        job_id: str,
        *,
        segment_id: str | None,
        category: str,
        severity: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        suggestion: str = "",
    ) -> str:
        issue_id = new_id()
        with self.workspace.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO review_issues(
                    id,job_id,segment_id,category,severity,message,evidence_json,suggestion,status,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    issue_id,
                    job_id,
                    segment_id,
                    category,
                    severity,
                    message,
                    json_text(evidence or {}),
                    suggestion,
                    "open",
                    utc_now(),
                ),
            )
        return issue_id

    def list_issues(self, job_id: str, *, include_resolved: bool = True) -> list[dict[str, Any]]:
        clause = "" if include_resolved else "AND status='open'"
        with self.workspace.session() as connection:
            rows = connection.execute(
                f"SELECT * FROM review_issues WHERE job_id=? {clause} ORDER BY created_at",
                (job_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = decode_json(item.pop("evidence_json"), {})
            result.append(item)
        return result

    def resolve_issue(self, issue_id: str, status: str) -> None:
        if status not in {"accepted", "dismissed", "resolved"}:
            raise FolioCrossError("invalid_issue_status", f"不支持的问题状态：{status}")
        with self.workspace.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE review_issues SET status=?,resolved_at=? WHERE id=?",
                (status, utc_now(), issue_id),
            ).rowcount
            if not changed:
                raise FolioCrossError("issue_not_found", f"找不到质量问题：{issue_id}")

    def update_issue_suggestion(self, issue_id: str, suggestion: str) -> None:
        with self.workspace.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE review_issues SET suggestion=? WHERE id=?", (suggestion, issue_id)
            ).rowcount
            if not changed:
                raise FolioCrossError("issue_not_found", f"找不到质量问题：{issue_id}")

    def unresolved_error_count(self, job_id: str) -> int:
        with self.workspace.session() as connection:
            return int(
                connection.execute(
                    """SELECT COUNT(*) FROM review_issues
                    WHERE job_id=? AND status='open' AND severity='error'""",
                    (job_id,),
                ).fetchone()[0]
            )

    def issue(self, issue_id: str) -> dict[str, Any]:
        with self.workspace.session() as connection:
            row = connection.execute(
                "SELECT * FROM review_issues WHERE id=?", (issue_id,)
            ).fetchone()
        if not row:
            raise FolioCrossError("issue_not_found", f"找不到质量问题：{issue_id}")
        item = dict(row)
        item["evidence"] = decode_json(item.pop("evidence_json"), {})
        return item

    def job_steps(self, job_id: str) -> list[dict[str, Any]]:
        with self.workspace.session() as connection:
            rows = connection.execute(
                "SELECT * FROM job_steps WHERE job_id=? ORDER BY rowid", (job_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, job_id: str, *, limit: int = 300) -> list[dict[str, Any]]:
        with self.workspace.session() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE job_id=? ORDER BY seq DESC LIMIT ?", (job_id, limit)
            ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            item["payload"] = decode_json(item.pop("payload_json"), {})
            result.append(item)
        return result

    def segment(self, segment_id: str) -> dict[str, Any]:
        with self.workspace.session() as connection:
            row = connection.execute("SELECT * FROM segments WHERE id=?", (segment_id,)).fetchone()
        if not row:
            raise FolioCrossError("segment_not_found", f"找不到段落：{segment_id}")
        return self._decode_segment(dict(row))

    def start_request(
        self,
        job_id: str,
        *,
        stage: str,
        model: str,
        input_hash: str,
        chapter_id: str | None,
        attempt: int,
    ) -> str:
        request_id = new_id()
        with self.workspace.transaction(immediate=True) as connection:
            job = connection.execute("SELECT currency FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise FolioCrossError("job_not_found", f"找不到任务：{job_id}")
            connection.execute(
                """INSERT INTO llm_requests(
                    id,job_id,chapter_id,stage,model,input_hash,status,attempt,currency,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    request_id,
                    job_id,
                    chapter_id,
                    stage,
                    model,
                    input_hash,
                    "pending",
                    attempt,
                    job["currency"],
                    utc_now(),
                ),
            )
        return request_id

    def finish_request(
        self,
        request_id: str,
        *,
        status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_hit_tokens: int = 0,
        cost: float | None = None,
        error_code: str | None = None,
    ) -> None:
        with self.workspace.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT job_id,stage,model,currency FROM llm_requests WHERE id=?", (request_id,)
            ).fetchone()
            if not row:
                return
            now = utc_now()
            connection.execute(
                """UPDATE llm_requests SET status=?,prompt_tokens=?,completion_tokens=?,
                    cache_hit_tokens=?,cost=?,error_code=?,finished_at=? WHERE id=?""",
                (
                    status,
                    prompt_tokens,
                    completion_tokens,
                    cache_hit_tokens,
                    cost,
                    error_code,
                    now,
                    request_id,
                ),
            )
            if prompt_tokens or completion_tokens or cache_hit_tokens or cost is not None:
                connection.execute(
                    """INSERT INTO usage_events(
                        id,request_id,job_id,stage,model,prompt_tokens,completion_tokens,
                        cache_hit_tokens,cost,currency,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        new_id(),
                        request_id,
                        row["job_id"],
                        row["stage"],
                        row["model"],
                        prompt_tokens,
                        completion_tokens,
                        cache_hit_tokens,
                        cost,
                        row["currency"],
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE jobs SET actual_cost=actual_cost+COALESCE(?,0),updated_at=? WHERE id=?",
                    (cost, now, row["job_id"]),
                )

    def usage_summary(self, job_id: str) -> dict[str, Any]:
        with self.workspace.session() as connection:
            total = connection.execute(
                """SELECT COALESCE(SUM(prompt_tokens),0) prompt_tokens,
                    COALESCE(SUM(completion_tokens),0) completion_tokens,
                    COALESCE(SUM(cache_hit_tokens),0) cache_hit_tokens,
                    SUM(cost) cost, MIN(currency) currency, COUNT(*) calls
                    FROM usage_events WHERE job_id=?""",
                (job_id,),
            ).fetchone()
            stages = connection.execute(
                """SELECT stage,model,SUM(prompt_tokens) prompt_tokens,
                    SUM(completion_tokens) completion_tokens,SUM(cache_hit_tokens) cache_hit_tokens,
                    SUM(cost) cost,COUNT(*) calls FROM usage_events WHERE job_id=?
                    GROUP BY stage,model ORDER BY stage,model""",
                (job_id,),
            ).fetchall()
            retries = connection.execute(
                "SELECT COUNT(*) FROM llm_requests WHERE job_id=? AND attempt>1", (job_id,)
            ).fetchone()[0]
            retry_usage = connection.execute(
                """SELECT COALESCE(SUM(u.prompt_tokens),0) prompt_tokens,
                    COALESCE(SUM(u.completion_tokens),0) completion_tokens,
                    COALESCE(SUM(u.cache_hit_tokens),0) cache_hit_tokens,
                    SUM(u.cost) cost, COUNT(*) calls
                    FROM usage_events u JOIN llm_requests r ON r.id=u.request_id
                    WHERE u.job_id=? AND r.attempt>1""",
                (job_id,),
            ).fetchone()
            chapters = connection.execute(
                """SELECT r.chapter_id,COALESCE(c.chapter_index,-1) chapter_index,
                    COALESCE(c.title,'全书任务') chapter_title,
                    SUM(u.prompt_tokens) prompt_tokens,
                    SUM(u.completion_tokens) completion_tokens,
                    SUM(u.cache_hit_tokens) cache_hit_tokens,SUM(u.cost) cost,COUNT(*) calls
                    FROM usage_events u JOIN llm_requests r ON r.id=u.request_id
                    LEFT JOIN chapters c ON c.id=r.chapter_id
                    WHERE u.job_id=?
                    GROUP BY r.chapter_id,c.chapter_index,c.title
                    ORDER BY chapter_index""",
                (job_id,),
            ).fetchall()
            requests = connection.execute(
                """SELECT r.id,r.chapter_id,c.title chapter_title,r.stage,r.model,r.status,
                    r.attempt,r.prompt_tokens,r.completion_tokens,r.cache_hit_tokens,r.cost,
                    r.currency,r.error_code,r.created_at,r.finished_at
                    FROM llm_requests r LEFT JOIN chapters c ON c.id=r.chapter_id
                    WHERE r.job_id=? ORDER BY r.created_at DESC,r.id DESC LIMIT 500""",
                (job_id,),
            ).fetchall()
            current_request = connection.execute(
                """SELECT r.id,r.chapter_id,c.title chapter_title,r.stage,r.model,r.status,
                    r.attempt,r.created_at FROM llm_requests r
                    LEFT JOIN chapters c ON c.id=r.chapter_id
                    WHERE r.job_id=? AND r.status='pending'
                    ORDER BY r.created_at DESC LIMIT 1""",
                (job_id,),
            ).fetchone()
        return {
            "total": dict(total),
            "by_stage_model": [dict(row) for row in stages],
            "by_chapter": [dict(row) for row in chapters],
            "requests": [dict(row) for row in requests],
            "current_request": dict(current_request) if current_request else None,
            "retries": retries,
            "retry_usage": dict(retry_usage),
        }

    def add_artifact(
        self,
        job_id: str,
        *,
        kind: str,
        format_name: str,
        path: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        artifact_id = new_id()
        digest = sha256_file(path) if Path(path).is_file() else None
        with self.workspace.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO artifacts(id,job_id,kind,format,path,sha256,metadata_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    artifact_id,
                    job_id,
                    kind,
                    format_name,
                    path,
                    digest,
                    json_text(metadata or {}),
                    utc_now(),
                ),
            )
        return artifact_id

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with self.workspace.session() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE job_id=? ORDER BY created_at DESC", (job_id,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = decode_json(item.pop("metadata_json", "{}"), {})
            result.append(item)
        return result

    def set_setting(self, key: str, value: Any) -> None:
        with self.workspace.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO settings(key,value_json,updated_at) VALUES (?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at""",
                (key, json_text(value), utc_now()),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.workspace.session() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key=?", (key,)
            ).fetchone()
        return decode_json(row[0], default) if row else default

    def emit_event(self, job_id: str | None, event_type: str, payload: dict[str, Any]) -> int:
        with self.workspace.transaction(immediate=True) as connection:
            return self._insert_event(connection, job_id, event_type, payload)

    @staticmethod
    def _insert_event(
        connection, job_id: str | None, event_type: str, payload: dict[str, Any]
    ) -> int:
        cursor = connection.execute(
            "INSERT INTO events(job_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
            (job_id, event_type, json_text(payload), utc_now()),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _decode_book(item: dict[str, Any]) -> dict[str, Any]:
        item["metadata"] = decode_json(item.pop("metadata_json", "{}"), {})
        item["warnings"] = decode_json(item.pop("warnings_json", "[]"), [])
        item["archived"] = bool(item.get("archived"))
        return item

    @staticmethod
    def _decode_job(item: dict[str, Any]) -> dict[str, Any]:
        item["config"] = decode_json(item.pop("config_json", "{}"), {})
        item["book_context"] = decode_json(item.pop("book_context_json", "{}"), {})
        item["glossary_snapshot"] = decode_json(item.pop("glossary_snapshot_json", "[]"), [])
        if "metadata_json" in item:
            item["metadata"] = decode_json(item.pop("metadata_json"), {})
        if "warnings_json" in item:
            item["warnings"] = decode_json(item.pop("warnings_json"), [])
        item["archived"] = bool(item.get("archived"))
        try:
            config = JobConfig.from_dict(item["config"])
            item["estimated_cost_peak"] = estimate_cost(
                config.profile,
                int(item.get("estimated_input_tokens") or 0),
                int(item.get("estimated_output_tokens") or 0),
                peak=True,
            )
            item["cost_configured"] = (
                config.profile.input_price_per_million is not None
                and config.profile.output_price_per_million is not None
            )
        except (TypeError, ValueError):
            item["estimated_cost_peak"] = None
            item["cost_configured"] = False
        started_at = item.get("started_at")
        finished_at = item.get("finished_at")
        completed = int(item.get("completed_segments") or 0)
        total = int(item.get("total_segments") or 0)
        elapsed = 0.0
        if started_at:
            try:
                started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                end = (
                    datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
                    if finished_at
                    else datetime.now(timezone.utc)
                )
                elapsed = max(0.0, (end - started).total_seconds())
            except ValueError:
                elapsed = 0.0
        speed = completed / elapsed * 60 if elapsed > 0 and completed else 0.0
        item["elapsed_seconds"] = round(elapsed, 1)
        item["segments_per_minute"] = round(speed, 2)
        item["eta_seconds"] = (
            round((total - completed) / speed * 60)
            if speed > 0 and completed < total and item.get("status") == JobStatus.TRANSLATING.value
            else None
        )
        return item

    @staticmethod
    def _decode_chapter(item: dict[str, Any]) -> dict[str, Any]:
        item["locator"] = decode_json(item.pop("locator_json", "{}"), {})
        item["segment_count"] = int(item.get("segment_count") or 0)
        item["translated_count"] = int(item.get("translated_count") or 0)
        return item

    @staticmethod
    def _decode_segment(item: dict[str, Any]) -> dict[str, Any]:
        item["locator"] = decode_json(item.pop("locator_json", "{}"), {})
        item["markers"] = decode_json(item.pop("markers_json", "[]"), [])
        item["quality"] = decode_json(item.pop("quality_json", "{}"), {})
        item["locked"] = bool(item["locked"])
        return item
