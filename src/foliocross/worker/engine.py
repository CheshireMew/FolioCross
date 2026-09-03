"""Crash-resumable, bounded-concurrency book translation worker."""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from ..application.quality import check_translation
from ..domain.models import DesiredState, JobConfig, JobStatus
from ..errors import FolioCrossError
from ..infrastructure.formats.common import batches
from ..infrastructure.formats.exporters import export_job
from ..infrastructure.formats.markers import repair_missing_markers, validate_markers
from ..infrastructure.llm import FakeClient, OpenAICompatibleClient, parse_json_content
from ..infrastructure.pricing import calculate_cost
from ..infrastructure.repository import Repository
from ..infrastructure.workspace import Workspace


class PauseRequested(Exception):
    pass


class CancelRequested(Exception):
    pass


class AdaptiveLimiter:
    def __init__(self, start: int, maximum: int) -> None:
        self.maximum = max(1, maximum)
        self.limit = min(self.maximum, max(1, start))
        self.active = 0
        self.successes = 0
        self.condition = threading.Condition()

    @contextmanager
    def slot(self) -> Iterator[None]:
        with self.condition:
            while self.active >= self.limit:
                self.condition.wait(timeout=0.5)
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def set_limit(self, value: int) -> None:
        with self.condition:
            self.limit = min(self.maximum, max(1, value))
            self.successes = 0
            self.condition.notify_all()

    def success(self) -> int:
        with self.condition:
            self.successes += 1
            if self.successes >= 20 and self.limit < self.maximum:
                self.limit += 1
                self.successes = 0
                self.condition.notify_all()
            return self.limit

    def rate_limited(self) -> int:
        with self.condition:
            self.limit = max(1, self.limit - 1)
            self.successes = 0
            self.condition.notify_all()
            return self.limit


class RequestGate:
    def __init__(self, rpm: int | None, tpm: int | None) -> None:
        self.rpm = rpm if rpm and rpm > 0 else None
        self.tpm = tpm if tpm and tpm > 0 else None
        self.requests: deque[float] = deque()
        self.tokens: deque[tuple[float, int]] = deque()
        self.lock = threading.Lock()

    def wait(self, estimated_tokens: int, check_control: Callable[[], None]) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.requests and now - self.requests[0] >= 60:
                    self.requests.popleft()
                while self.tokens and now - self.tokens[0][0] >= 60:
                    self.tokens.popleft()
                request_ok = self.rpm is None or len(self.requests) < self.rpm
                token_ok = (
                    self.tpm is None
                    or sum(item[1] for item in self.tokens) + estimated_tokens <= self.tpm
                )
                if request_ok and token_ok:
                    self.requests.append(now)
                    self.tokens.append((now, estimated_tokens))
                    return
            check_control()
            time.sleep(0.25)


class WorkerEventEmitter:
    def __init__(
        self, repository: Repository, sink: Callable[[dict[str, Any]], None] | None = None
    ) -> None:
        self.repository = repository
        self.sink = sink
        self.lock = threading.Lock()

    def emit(
        self, job_id: str, event_type: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = payload or {}
        with self.lock:
            sequence = self.repository.emit_event(job_id, event_type, payload)
            event = {
                "protocol_version": 1,
                "type": event_type,
                "job_id": job_id,
                "seq": sequence,
                "timestamp": time.time(),
                "payload": payload,
            }
            if self.sink:
                self.sink(event)
            self.repository.update_job(job_id, heartbeat=True)
            return event


@contextmanager
def job_lock(workspace: Workspace, job_id: str) -> Iterator[None]:
    lock_dir = workspace.jobs_dir / job_id
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / "worker.lock"
    stream = path.open("a+b")
    stream.seek(0)
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise FolioCrossError(
                    "job_already_running", "该任务已经由另一个 Worker 运行。"
                ) from error
        else:  # pragma: no cover
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise FolioCrossError(
                    "job_already_running", "该任务已经由另一个 Worker 运行。"
                ) from error
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


class LLMRuntime:
    def __init__(
        self,
        repository: Repository,
        job_id: str,
        config: JobConfig,
        emitter: WorkerEventEmitter,
        *,
        honor_job_control: bool = True,
    ) -> None:
        self.repository = repository
        self.job_id = job_id
        self.config = config
        self.profile = config.profile
        self.emitter = emitter
        self.honor_job_control = honor_job_control
        self.limiter = AdaptiveLimiter(
            config.translation_start_concurrency, config.translation_max_concurrency
        )
        self.gate = RequestGate(config.requests_per_minute, config.tokens_per_minute)
        self._budget_lock = threading.Lock()
        self._soft_budget_warned = False
        self.client = (
            FakeClient()
            if self.profile.provider == "fake"
            else OpenAICompatibleClient(self.profile)
        )

    def check_control(self) -> None:
        if self.honor_job_control:
            desired = self.repository.desired_state(self.job_id)
            if desired == DesiredState.PAUSE.value:
                raise PauseRequested
            if desired == DesiredState.CANCEL.value:
                raise CancelRequested
        soft_budget = self.config.soft_budget
        hard_budget = self.config.hard_budget
        if soft_budget is not None or hard_budget is not None:
            cost = self.repository.get_job(self.job_id)["actual_cost"]
        if soft_budget is not None and cost >= soft_budget:
            with self._budget_lock:
                if not self._soft_budget_warned:
                    self._soft_budget_warned = True
                    self.emitter.emit(
                        self.job_id,
                        "warning.raised",
                        {
                            "code": "soft_budget_reached",
                            "message": "已达到费用提醒值，任务会继续运行。",
                            "cost": cost,
                            "soft_budget": soft_budget,
                        },
                    )
        if hard_budget is not None:
            if cost >= hard_budget:
                self.repository.set_desired_state(self.job_id, DesiredState.PAUSE)
                self.emitter.emit(
                    self.job_id,
                    "warning.raised",
                    {
                        "code": "hard_budget_reached",
                        "message": "达到任务费用上限，已暂停。",
                        "cost": cost,
                    },
                )
                if self.honor_job_control:
                    raise PauseRequested
                raise FolioCrossError(
                    "hard_budget_reached", "达到任务费用上限，没有继续发起模型请求。"
                )

    def call_json(
        self,
        *,
        stage: str,
        model: str,
        system: str,
        payload: dict[str, Any],
        chapter_id: str | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        user = json.dumps(payload, ensure_ascii=False)
        input_hash = hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest()
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 2):
            self.check_control()
            self.gate.wait(max(1, len(system + user) // 3), self.check_control)
            request_id = self.repository.start_request(
                self.job_id,
                stage=stage,
                model=model,
                input_hash=input_hash,
                chapter_id=chapter_id,
                attempt=attempt,
            )
            response = None
            cost = None
            try:
                with self.limiter.slot():
                    response = self.client.complete(
                        model=model,
                        system=system,
                        user=user,
                        json_mode=True,
                        max_tokens=max_tokens,
                    )
                cost = self._cost(response.usage)
                parsed = parse_json_content(response.content)
                self.repository.finish_request(
                    request_id,
                    status="succeeded",
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    cache_hit_tokens=response.usage.cache_hit_tokens,
                    cost=cost,
                )
                limit = self.limiter.success()
                self.emitter.emit(
                    self.job_id,
                    "usage.recorded",
                    {
                        "stage": stage,
                        "model": model,
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "cache_hit_tokens": response.usage.cache_hit_tokens,
                        "cost": cost,
                        "currency": self.profile.currency,
                        "attempt": attempt,
                        "concurrency": limit,
                    },
                )
                return parsed
            except (PauseRequested, CancelRequested):
                self.repository.finish_request(
                    request_id, status="aborted", error_code="controlled_stop"
                )
                raise
            except Exception as error:
                last_error = error
                status_code = getattr(error, "status_code", None)
                code = getattr(error, "code", None) or type(error).__name__
                if response is None:
                    self.repository.finish_request(
                        request_id, status="failed", error_code=str(code)
                    )
                else:
                    self.repository.finish_request(
                        request_id,
                        status="failed",
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        cache_hit_tokens=response.usage.cache_hit_tokens,
                        cost=cost,
                        error_code=str(code),
                    )
                retryable = status_code in {408, 409, 429, 500, 502, 503, 504} or isinstance(
                    error, (TimeoutError, ConnectionError)
                )
                if code in {"invalid_json", "empty_response"}:
                    retryable = True
                if status_code == 429 or "429" in str(error):
                    limit = self.limiter.rate_limited()
                    self.emitter.emit(
                        self.job_id,
                        "warning.raised",
                        {
                            "code": "rate_limited",
                            "message": "服务端限流，正在降低并发。",
                            "concurrency": limit,
                        },
                    )
                    retryable = True
                if not retryable or attempt > self.config.max_retries:
                    raise
                retry_after = _retry_after(error)
                delay = (
                    retry_after
                    if retry_after is not None
                    else min(60.0, (2 ** (attempt - 1)) + random.random())
                )
                self.emitter.emit(
                    self.job_id,
                    "warning.raised",
                    {
                        "code": "request_retry",
                        "message": f"请求失败，{delay:.1f} 秒后重试。",
                        "attempt": attempt + 1,
                    },
                )
                self._controlled_wait(delay)
        assert last_error is not None
        raise last_error

    def _controlled_wait(self, delay: float) -> None:
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            self.check_control()
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))

    def _cost(self, usage) -> float | None:
        return calculate_cost(self.profile, usage)


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None)
    if headers:
        try:
            return max(0.0, float(headers.get("retry-after")))
        except (TypeError, ValueError):
            return None
    return None


class WorkerEngine:
    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.workspace = workspace or Workspace.default()
        self.repository = Repository(self.workspace)
        self.emitter = WorkerEventEmitter(self.repository, event_sink)

    def run(self, job_id: str, *, export_when_done: bool = True) -> dict[str, Any]:
        with job_lock(self.workspace, job_id):
            job = self.repository.get_job(job_id)
            config = JobConfig.from_dict(job["config"])
            runtime = LLMRuntime(self.repository, job_id, config, self.emitter)
            self.repository.set_desired_state(job_id, DesiredState.RUN)
            self.emitter.emit(job_id, "job.started", {"preset": config.preset})
            try:
                self._prepare(job_id, runtime)
                self._translate(job_id, runtime)
                self._quality(job_id, runtime)
                output = self._export(job_id, config) if export_when_done else None
                self.repository.update_job(
                    job_id,
                    status=JobStatus.COMPLETED.value if export_when_done else JobStatus.READY.value,
                    stage="completed" if export_when_done else "ready",
                    message="翻译与导出完成" if export_when_done else "翻译完成，可以导出",
                    finished=export_when_done,
                )
                self.emitter.emit(job_id, "job.completed", {"output": output})
                return {"ok": True, "job_id": job_id, "status": "completed", "output": output}
            except PauseRequested:
                self.repository.update_job(
                    job_id, status=JobStatus.PAUSED.value, message="已在安全检查点暂停"
                )
                self.emitter.emit(job_id, "job.paused", {})
                return {"ok": True, "job_id": job_id, "status": "paused"}
            except CancelRequested:
                self.repository.update_job(
                    job_id,
                    status=JobStatus.CANCELLED.value,
                    stage="cancelled",
                    message="任务已取消，已有结果保留",
                    finished=True,
                )
                self.emitter.emit(job_id, "job.cancelled", {})
                return {"ok": True, "job_id": job_id, "status": "cancelled"}
            except Exception as error:
                code = error.code if isinstance(error, FolioCrossError) else type(error).__name__
                message = error.message if isinstance(error, FolioCrossError) else str(error)
                self.repository.update_job(
                    job_id,
                    status=JobStatus.FAILED.value,
                    message=message,
                    error_code=str(code),
                    error_message=message,
                )
                self.emitter.emit(job_id, "job.failed", {"code": str(code), "message": message})
                raise

    def deep_review(self, job_id: str) -> dict[str, Any]:
        """Run an explicit semantic review and only create actionable issues."""

        with job_lock(self.workspace, job_id):
            job = self.repository.get_job(job_id)
            config = JobConfig.from_dict(job["config"])
            runtime = LLMRuntime(
                self.repository,
                job_id,
                config,
                self.emitter,
                honor_job_control=False,
            )
            chapters = self.repository.chapters_for_job(job_id)
            translated = [
                segment
                for chapter in chapters
                for segment in self.repository.segments_for_chapter(chapter["id"])
                if segment["target_text"]
            ]
            if not translated:
                raise FolioCrossError("review_not_ready", "还没有可审校的译文。")
            original_status = job["status"]
            original_stage = job["stage"]
            self.repository.update_job(
                job_id,
                status=JobStatus.QUALITY_CHECK.value,
                stage="deep_review",
                message="正在执行用户主动启动的深度审校",
            )
            self.emitter.emit(
                job_id,
                "stage.changed",
                {"stage": "deep_review", "model": config.profile.review_model},
            )
            created = 0
            try:
                for batch in batches(translated, config.max_chars_per_batch):
                    payload = {
                        "book_context": job.get("book_context", {}),
                        "review_segments": [
                            {
                                "id": segment["id"],
                                "source": segment["source_text"],
                                "translation": segment["target_text"],
                            }
                            for segment in batch
                        ],
                    }
                    data = runtime.call_json(
                        stage="deep_review",
                        model=config.profile.review_model,
                        system=(
                            "审校这些译文，只报告有原文证据、值得人工处理的问题，不做全文润色。"
                            "返回 issues 数组；每项必须含 segment_id、category、severity、message、"
                            "evidence 和 suggestion。suggestion 必须是可直接替换该段的完整译文。"
                        ),
                        payload=payload,
                    )
                    valid_ids = {segment["id"] for segment in batch}
                    issues = data.get("issues", [])
                    if not isinstance(issues, list):
                        continue
                    for item in issues:
                        if not isinstance(item, dict) or item.get("segment_id") not in valid_ids:
                            continue
                        severity = str(item.get("severity", "warning"))
                        if severity not in {"warning", "error"}:
                            severity = "warning"
                        self.repository.create_issue(
                            job_id,
                            segment_id=str(item["segment_id"]),
                            category=str(item.get("category", "semantic_review")),
                            severity=severity,
                            message=str(item.get("message", "模型建议人工检查。")),
                            evidence=(
                                item.get("evidence")
                                if isinstance(item.get("evidence"), dict)
                                else {"text": str(item.get("evidence", ""))}
                            ),
                            suggestion=str(item.get("suggestion", "")),
                        )
                        created += 1
                self.emitter.emit(job_id, "review.completed", {"issues_created": created})
                return {"ok": True, "job_id": job_id, "issues_created": created}
            finally:
                self.repository.update_job(
                    job_id,
                    status=original_status,
                    stage=original_stage,
                    message=f"深度审校完成，新增 {created} 个待检查问题",
                )

    def prepare_only(self, job_id: str) -> dict[str, Any]:
        """Build the book context and frozen glossary, then stop at a safe boundary."""

        with job_lock(self.workspace, job_id):
            job = self.repository.get_job(job_id)
            config = JobConfig.from_dict(job["config"])
            runtime = LLMRuntime(self.repository, job_id, config, self.emitter)
            self.repository.set_desired_state(job_id, DesiredState.RUN)
            self.emitter.emit(job_id, "job.started", {"mode": "prepare_only"})
            try:
                self._prepare(job_id, runtime)
                self.repository.set_desired_state(job_id, DesiredState.PAUSE)
                self.repository.update_job(
                    job_id,
                    status=JobStatus.PAUSED.value,
                    stage="prepared",
                    message="译前准备完成，请检查术语后再继续翻译",
                )
                self.emitter.emit(job_id, "job.paused", {"reason": "prepare_only_complete"})
                return {"ok": True, "job_id": job_id, "status": "prepared"}
            except PauseRequested:
                self.repository.update_job(
                    job_id, status=JobStatus.PAUSED.value, message="已在安全检查点暂停"
                )
                self.emitter.emit(job_id, "job.paused", {})
                return {"ok": True, "job_id": job_id, "status": "paused"}
            except CancelRequested:
                self.repository.update_job(
                    job_id,
                    status=JobStatus.CANCELLED.value,
                    stage="cancelled",
                    message="任务已取消，译前准备结果保留",
                    finished=True,
                )
                self.emitter.emit(job_id, "job.cancelled", {})
                return {"ok": True, "job_id": job_id, "status": "cancelled"}
            except Exception as error:
                code = error.code if isinstance(error, FolioCrossError) else type(error).__name__
                message = error.message if isinstance(error, FolioCrossError) else str(error)
                self.repository.update_job(
                    job_id,
                    status=JobStatus.FAILED.value,
                    message=message,
                    error_code=str(code),
                    error_message=message,
                )
                self.emitter.emit(job_id, "job.failed", {"code": str(code), "message": message})
                raise

    def retranslate_segment(
        self, job_id: str, segment_id: str, instruction: str = ""
    ) -> dict[str, Any]:
        """Retranslate one segment and preserve the result as a locked revision."""

        with job_lock(self.workspace, job_id):
            job = self.repository.get_job(job_id)
            segment = self.repository.segment_context(segment_id)
            if segment["job_id"] != job_id:
                raise FolioCrossError("segment_job_mismatch", "该段落不属于当前任务。")
            config = JobConfig.from_dict(job["config"])
            runtime = LLMRuntime(
                self.repository,
                job_id,
                config,
                self.emitter,
                honor_job_control=False,
            )
            terms = self.repository.relevant_glossary(job_id, segment["source_text"])
            data = runtime.call_json(
                stage="retranslation",
                model=config.profile.translation_model,
                system=(
                    "重新翻译一个段落为自然、准确的简体中文。遵守术语表和用户要求，"
                    "原样保留所有 ⟦FC:...⟧ 标记。返回 translation。"
                ),
                payload={
                    "retranslate_source": segment["source_text"],
                    "current_translation": segment["target_text"],
                    "instruction": instruction.strip(),
                    "book_context": segment["book_context"],
                    "chapter": {
                        "title": segment["chapter_title"],
                        "summary": segment["chapter_summary"],
                    },
                    "glossary": [
                        {"source": item["source"], "target": item["target"]} for item in terms
                    ],
                },
                chapter_id=segment["chapter_id"],
            )
            translation = str(data.get("translation", "")).strip()
            if not translation:
                raise FolioCrossError("empty_response", "模型没有返回可用的重译结果。")
            chapter = {"id": segment["chapter_id"], "title": segment["chapter_title"]}
            translation, issues = self._validate_and_repair(
                job_id, chapter, segment, translation, terms, runtime
            )
            version = self.repository.save_segment_revision(
                segment_id,
                translation,
                origin="retranslation",
                model=config.profile.translation_model,
                instruction=instruction.strip(),
                lock=True,
                quality={"issues": issues},
                allow_locked=True,
            )
            self.emitter.emit(
                job_id,
                "segment.retranslated",
                {"segment_id": segment_id, "version": version},
            )
            return {
                "ok": True,
                "job_id": job_id,
                "segment_id": segment_id,
                "version": version,
                "translation": translation,
            }

    def export_only(self, job_id: str, format_name: str) -> dict[str, Any]:
        """Re-export committed translations without invoking a model."""

        with job_lock(self.workspace, job_id):
            job = self.repository.get_job(job_id)
            original_status = job["status"]
            original_stage = job["stage"]
            self.repository.update_job(
                job_id,
                status=JobStatus.EXPORTING.value,
                stage="export",
                message=f"正在重新生成 {format_name.upper()}",
            )
            try:
                output = export_job(self.repository, job_id, format_name)
                self.repository.add_artifact(
                    job_id, kind="translation", format_name=format_name, path=output
                )
                self.emitter.emit(
                    job_id, "export.completed", {"format": format_name, "output": output}
                )
                return {"ok": True, "job_id": job_id, "format": format_name, "output": output}
            finally:
                self.repository.update_job(
                    job_id,
                    status=original_status,
                    stage=original_stage,
                    message=f"已重新生成 {format_name.upper()}",
                )

    def _prepare(self, job_id: str, runtime: LLMRuntime) -> None:
        chapters = self.repository.chapters_for_job(job_id)
        missing = [chapter for chapter in chapters if not chapter["summary"]]
        if not missing and self.repository.get_job(job_id).get("book_context"):
            return
        self.repository.update_job(
            job_id,
            status=JobStatus.PREPARING.value,
            stage="prepare",
            message="理解全书并建立术语表",
        )
        self.repository.update_step(
            job_id,
            "prepare",
            status="running",
            completed=len(chapters) - len(missing),
            total=len(chapters),
        )
        self.emitter.emit(
            job_id, "stage.changed", {"stage": "prepare", "message": "理解全书并建立术语表"}
        )
        runtime.limiter.set_limit(
            min(runtime.config.prescan_concurrency, runtime.config.translation_max_concurrency)
        )

        def scan(chapter: dict[str, Any]) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
            runtime.check_control()
            segments = self.repository.segments_for_chapter(chapter["id"])
            full_text = "\n".join(item["source_text"] for item in segments)
            if len(full_text) > 16_000:
                full_text = full_text[:8_000] + "\n…\n" + full_text[-8_000:]
            payload = {
                "chapter_index": chapter["chapter_index"],
                "chapter_title": chapter["title"],
                "chapter_text": full_text,
            }
            data = runtime.call_json(
                stage="preparation",
                model=runtime.profile.analysis_model,
                system=(
                    "你负责为整本书的翻译做一次低成本译前准备。概括本章，并抽取会在后文重复出现、"
                    "必须统一译名的人名、地名、组织、作品名和专业术语。不要抽普通词。"
                    "返回 summary 和 terms；每个 term 含 source、target、type、confidence、frequency。"
                ),
                payload=payload,
                chapter_id=chapter["id"],
                max_tokens=1800,
            )
            summary = str(data.get("summary", "")).strip() or "（无有效梗概）"
            terms = data.get("terms", []) if isinstance(data.get("terms"), list) else []
            for term in terms:
                if isinstance(term, dict):
                    term["chapter_index"] = chapter["chapter_index"]
            return chapter, summary, [item for item in terms if isinstance(item, dict)]

        completed = len(chapters) - len(missing)
        with ThreadPoolExecutor(max_workers=max(1, runtime.config.prescan_concurrency)) as executor:
            futures = [executor.submit(scan, chapter) for chapter in missing]
            for future in as_completed(futures):
                chapter, summary, terms = future.result()
                self.repository.update_chapter_summary(chapter["id"], summary)
                self.repository.upsert_glossary_terms(job_id, terms)
                completed += 1
                self.repository.update_step(
                    job_id, "prepare", status="running", completed=completed, total=len(chapters)
                )
                self.emitter.emit(
                    job_id,
                    "progress.updated",
                    {
                        "stage": "prepare",
                        "completed": completed,
                        "total": len(chapters),
                        "chapter": chapter["title"],
                    },
                )

        summaries = [
            {"index": item["chapter_index"], "title": item["title"], "summary": item["summary"]}
            for item in self.repository.chapters_for_job(job_id)
        ]
        overview = runtime.call_json(
            stage="preparation",
            model=runtime.profile.analysis_model,
            system="根据各章梗概生成供译者使用的全书概览、文体说明和人物关系。返回 overview、style、characters。",
            payload={"chapter_summaries": summaries},
            max_tokens=1600,
        )
        self.repository.update_book_context(job_id, overview)
        self.repository.update_step(
            job_id,
            "prepare",
            status="done",
            completed=len(chapters),
            total=len(chapters),
            message="术语表已冻结",
        )
        runtime.limiter.set_limit(runtime.config.translation_start_concurrency)

    def _translate(self, job_id: str, runtime: LLMRuntime) -> None:
        chapters = self.repository.pending_chapters(job_id)
        total = self.repository.get_job(job_id)["total_segments"]
        if not chapters:
            return
        self.repository.update_job(
            job_id, status=JobStatus.TRANSLATING.value, stage="translate", message="正在翻译正文"
        )
        self.repository.update_step(
            job_id,
            "translate",
            status="running",
            completed=self.repository.get_job(job_id)["completed_segments"],
            total=total,
        )
        self.emitter.emit(
            job_id, "stage.changed", {"stage": "translate", "message": "正在翻译正文"}
        )
        runtime.limiter.set_limit(runtime.config.translation_start_concurrency)
        with ThreadPoolExecutor(
            max_workers=max(1, runtime.config.translation_max_concurrency)
        ) as executor:
            future_map = {
                executor.submit(self._translate_chapter, job_id, chapter, runtime): chapter
                for chapter in chapters
            }
            for future in as_completed(future_map):
                future.result()
                progress = self.repository.get_job(job_id)["completed_segments"]
                chapter = future_map[future]
                self.repository.update_step(
                    job_id, "translate", status="running", completed=progress, total=total
                )
                self.emitter.emit(
                    job_id,
                    "progress.updated",
                    {
                        "stage": "translate",
                        "completed": progress,
                        "total": total,
                        "chapter": chapter["title"],
                    },
                )
        self.repository.update_step(
            job_id, "translate", status="done", completed=total, total=total
        )

    def _translate_chapter(self, job_id: str, chapter: dict[str, Any], runtime: LLMRuntime) -> None:
        segments = self.repository.segments_for_chapter(chapter["id"])
        for batch in batches(segments, runtime.config.max_chars_per_batch):
            runtime.check_control()
            pending = [item for item in batch if not item["target_text"]]
            if not pending:
                continue
            previous = [
                item["target_text"]
                for item in segments
                if item["segment_index"] < pending[0]["segment_index"] and item["target_text"]
            ]
            previous = previous[-runtime.config.rolling_context_segments :]
            source_text = "\n".join(item["source_text"] for item in pending)
            terms = self.repository.relevant_glossary(job_id, source_text)
            payload = {
                "book_context": self.repository.get_job(job_id).get("book_context", {}),
                "chapter": {"title": chapter["title"], "summary": chapter["summary"]},
                "previous_translation": previous,
                "glossary": [
                    {"source": item["source"], "target": item["target"], "type": item["term_type"]}
                    for item in terms
                ],
                "segments": [{"id": item["id"], "text": item["source_text"]} for item in pending],
            }
            translations = self._translate_payload(runtime, chapter["id"], payload, len(pending))
            for segment, target in zip(pending, translations):
                segment_terms = [term for term in terms if term["source"] in segment["source_text"]]
                target, issues = self._validate_and_repair(
                    job_id, chapter, segment, str(target), segment_terms, runtime
                )
                quality = {"issues": issues}
                self.repository.save_segment_revision(
                    segment["id"],
                    target,
                    origin="model_translation",
                    model=runtime.profile.translation_model,
                    quality=quality,
                )
                for issue in issues:
                    self.repository.create_issue(
                        job_id,
                        segment_id=segment["id"],
                        category=issue["category"],
                        severity=issue["severity"],
                        message=issue["message"],
                    )

    @staticmethod
    def _translate_payload(
        runtime: LLMRuntime, chapter_id: str, payload: dict[str, Any], expected: int
    ) -> list[str]:
        for _ in range(3):
            data = runtime.call_json(
                stage="translation",
                model=runtime.profile.translation_model,
                system=(
                    "把输入段落翻译成自然、准确、可出版的简体中文。保持段落数量和顺序。"
                    "所有形如 ⟦FC:...⟧ 的标记必须逐字保留并保持相对顺序。遵守术语表，不扩写、不省略。"
                    "返回 translations 字符串数组。"
                ),
                payload=payload,
                chapter_id=chapter_id,
            )
            values = data.get("translations")
            if (
                isinstance(values, list)
                and len(values) == expected
                and all(isinstance(item, str) for item in values)
            ):
                return values
        raise FolioCrossError("translation_alignment_failed", "模型连续返回错误的段落数量。")

    def _validate_and_repair(
        self,
        job_id: str,
        chapter: dict[str, Any],
        segment: dict[str, Any],
        target: str,
        terms: list[dict[str, Any]],
        runtime: LLMRuntime,
    ) -> tuple[str, list[dict[str, str]]]:
        marker_issues = validate_markers(target, segment["markers"])
        marker_fallback_used = False
        if marker_issues:
            try:
                data = runtime.call_json(
                    stage="annotation_repair",
                    model=runtime.profile.repair_model,
                    system="只修复译文中缺失或错位的 ⟦FC:...⟧ 标记，不改写译文。返回 translation。",
                    payload={
                        "source": segment["source_text"],
                        "target": target,
                        "markers": [item["token"] for item in segment["markers"]],
                    },
                    chapter_id=chapter["id"],
                )
                candidate = data.get("translation")
                if isinstance(candidate, str) and not validate_markers(
                    candidate, segment["markers"]
                ):
                    target = candidate
                else:
                    target = repair_missing_markers(
                        segment["source_text"], target, segment["markers"]
                    )
                    marker_fallback_used = True
            except Exception:
                target = repair_missing_markers(segment["source_text"], target, segment["markers"])
                marker_fallback_used = True
        issues = check_translation(segment["source_text"], target, segment["markers"], terms)
        if marker_fallback_used:
            issues.append(
                {
                    "category": "marker_fallback",
                    "severity": "warning",
                    "message": "脚注或行内标记由位置回退规则恢复，请人工检查位置。",
                }
            )
        if any(item["severity"] == "error" and item["category"] != "marker" for item in issues):
            try:
                data = runtime.call_json(
                    stage="targeted_repair",
                    model=runtime.profile.repair_model,
                    system="根据明确的检查问题修复这一段简体中文译文。不得扩写，保留全部 ⟦FC:...⟧ 标记。返回 translation。",
                    payload={
                        "source": segment["source_text"],
                        "target": target,
                        "issues": issues,
                        "glossary": terms,
                    },
                    chapter_id=chapter["id"],
                )
                candidate = data.get("translation")
                if isinstance(candidate, str) and candidate.strip():
                    target = candidate
                    issues = check_translation(
                        segment["source_text"], target, segment["markers"], terms
                    )
            except Exception:
                pass
        return target, issues

    def _quality(self, job_id: str, runtime: LLMRuntime) -> None:
        runtime.check_control()
        self.repository.update_job(
            job_id, status=JobStatus.QUALITY_CHECK.value, stage="quality", message="汇总质量检查"
        )
        self.repository.update_step(job_id, "quality", status="running")
        self.emitter.emit(job_id, "stage.changed", {"stage": "quality", "message": "汇总质量检查"})
        issues = self.repository.list_issues(job_id, include_resolved=False)
        self.repository.update_step(
            job_id,
            "quality",
            status="done",
            completed=len(issues),
            total=len(issues),
            message=f"发现 {len(issues)} 个待检查项",
        )

    def _export(self, job_id: str, config: JobConfig) -> str:
        self.repository.update_job(
            job_id, status=JobStatus.EXPORTING.value, stage="export", message="正在生成成品"
        )
        self.repository.update_step(job_id, "export", status="running")
        self.emitter.emit(job_id, "stage.changed", {"stage": "export", "message": "正在生成成品"})
        output = export_job(self.repository, job_id, config.output_format)
        self.repository.add_artifact(
            job_id, kind="translation", format_name=config.output_format, path=output
        )
        self.repository.update_step(
            job_id, "export", status="done", completed=1, total=1, message=output
        )
        return output


def stdout_event_sink(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()
