"""QML-facing controller. Heavy operations always run in child processes."""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup
from docx import Document
from PySide6.QtCore import Property, QObject, QProcess, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ..application.service import FolioCrossService
from ..errors import FolioCrossError, localized_error
from ..infrastructure.formats.markers import restore_protected_markers, strip_protected_markers
from ..infrastructure.workspace import Workspace
from ..worker.scheduler import ensure_scheduler

TEXTS = {
    "zh-CN": {
        "library": "书库",
        "settings": "设置",
        "import_book": "导入书籍",
        "empty_library": "把一本书拖到这里，开始创建简体中文译本",
        "overview": "总览",
        "editor": "阅读编辑",
        "glossary": "术语",
        "quality": "质量",
        "usage": "用量",
        "outputs": "输出",
        "logs": "日志",
    },
    "en": {
        "library": "Library",
        "settings": "Settings",
        "import_book": "Import book",
        "empty_library": "Drop a book here to create a Simplified Chinese edition",
        "overview": "Overview",
        "editor": "Editor",
        "glossary": "Glossary",
        "quality": "Quality",
        "usage": "Usage",
        "outputs": "Outputs",
        "logs": "Logs",
    },
}

RUNTIME_TEXT_EN = {
    "API Key 已保存到 Windows 凭据管理器。": "The API key was saved to Windows Credential Manager.",
    "Worker 已停止；在途请求可能已产生费用。": "The Worker was stopped. An in-flight request may still have incurred usage.",
    "任务已归档，书籍和所有译文仍保留在工作区。": "The job was archived. The book and all translations remain in the workspace.",
    "任务已进入后台队列，关闭界面后仍会继续。": "The job is queued in the background and will continue after this window closes.",
    "任务将停止，已经完成的译文会保留。": "The job will stop at a safe checkpoint. Completed translations will be kept.",
    "任务运行期间不能修改配置。": "Pause the job before changing its settings.",
    "修改建议已作为人工锁定版本应用。": "The edited suggestion was applied as a manually locked revision.",
    "后台操作已完成。": "The background operation completed.",
    "后台操作失败，请查看任务日志。": "The background operation failed. See the job log for details.",
    "将在当前请求结束后暂停。": "The job will pause after the current request reaches a safe checkpoint.",
    "当前没有质量问题。": "There are no quality issues.",
    "排队中的后台操作已停止。": "The queued background operation was stopped.",
    "正在停止 Worker；在途请求可能已产生费用。": "Stopping the Worker. An in-flight request may still incur usage.",
    "模型与价格设置已保存，将用于之后新建的任务。": "The model and pricing settings were saved for new jobs.",
    "首次启动设置已完成。": "First-run setup is complete.",
    "同时运行书籍数已保存。": "The simultaneous-book limit was saved.",
    "翻译设置已保存。": "The translation settings were saved.",
    "译前准备已进入后台队列。": "Book preparation is queued in the background.",
    "这本书当前没有正在运行的 Worker。": "This book does not currently have a running Worker.",
    "连接检查返回了无法识别的结果。": "The connection check returned an unrecognized response.",
}


class DesktopController(QObject):
    jobsChanged = Signal()
    detailsChanged = Signal()
    busyChanged = Signal()
    message = Signal(str, str)
    importFinished = Signal(str)
    workerEvent = Signal(str, str)
    historyReady = Signal("QVariantList")
    affectedSegmentsReady = Signal("QVariantList")
    languageChanged = Signal()
    scaleChanged = Signal()
    themeChanged = Signal()

    def __init__(
        self,
        workspace: Workspace,
        *,
        scheduler_starter: Callable[[Workspace], int] | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.service = FolioCrossService(workspace)
        self._scheduler_starter = scheduler_starter or ensure_scheduler
        self._jobs: list[dict[str, Any]] = []
        self._selected: dict[str, Any] = {}
        self._chapters: list[dict[str, Any]] = []
        self._segments: list[dict[str, Any]] = []
        self._selected_chapter_id = ""
        self._glossary: list[dict[str, Any]] = []
        self._glossary_total = 0
        self._glossary_query = ""
        self._glossary_page_size = 100
        self._issues: list[dict[str, Any]] = []
        self._usage: dict[str, Any] = {}
        self._artifacts: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._steps: list[dict[str, Any]] = []
        self._busy = False
        self._language = self.service.repository.get_setting("ui_language", "zh-CN")
        self._ui_scale = float(self.service.repository.get_setting("ui_scale", 1.0) or 1.0)
        self._dark_mode = bool(self.service.repository.get_setting("dark_mode", False))
        self._processes: dict[str, QProcess] = {}
        self._cover_urls: dict[str, str] = {}
        self._job_statuses: dict[str, str] = {}
        self._refresh_initialized = False
        self.refresh()
        self._last_event_sequence = self.service.repository.latest_event_sequence()
        last_job = str(self.service.repository.get_setting("last_job_id", "") or "")
        if last_job and any(job["id"] == last_job for job in self._jobs):
            self.selectJob(last_job)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(750)
        self._poll_timer.timeout.connect(self._poll_jobs)
        self._poll_timer.start()
        QTimer.singleShot(0, self._start_next_queued)

    @Property("QVariantList", notify=jobsChanged)
    def jobs(self):
        return self._jobs

    @Property("QVariantMap", notify=detailsChanged)
    def selectedJob(self):
        return self._selected

    @Property("QVariantList", notify=detailsChanged)
    def chapters(self):
        return self._chapters

    @Property("QVariantList", notify=detailsChanged)
    def segments(self):
        return self._segments

    @Property(str, notify=detailsChanged)
    def selectedChapterId(self) -> str:
        return self._selected_chapter_id

    @Property("QVariantList", notify=detailsChanged)
    def glossary(self):
        return self._glossary

    @Property(int, notify=detailsChanged)
    def glossaryTotal(self) -> int:
        return self._glossary_total

    @Property("QVariantList", notify=detailsChanged)
    def issues(self):
        return self._issues

    @Property("QVariantMap", notify=detailsChanged)
    def usage(self):
        return self._usage

    @Property("QVariantList", notify=detailsChanged)
    def artifacts(self):
        return self._artifacts

    @Property("QVariantList", notify=detailsChanged)
    def events(self):
        return self._events

    @Property("QVariantList", notify=detailsChanged)
    def steps(self):
        return self._steps

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(bool, constant=True)
    def firstRun(self) -> bool:
        return not bool(self.service.repository.get_setting("first_run_complete", False))

    @Property(str, notify=languageChanged)
    def uiLanguage(self) -> str:
        return self._language

    @Property(float, notify=scaleChanged)
    def uiScale(self) -> float:
        return self._ui_scale

    @Property(bool, notify=themeChanged)
    def darkMode(self) -> bool:
        return self._dark_mode

    @Slot(str, result=str)
    def t(self, key: str) -> str:
        return TEXTS.get(self._language, TEXTS["zh-CN"]).get(key, key)

    @Slot(str, result=str)
    def localizeText(self, value: str) -> str:
        text = str(value or "")
        if self._language != "en" or not text:
            return text
        if text in RUNTIME_TEXT_EN:
            return RUNTIME_TEXT_EN[text]
        patterns = (
            (r"^已导入《(.+)》$", r"Imported “\1”."),
            (r"^已打开现有任务《(.+)》$", r"Opened the existing job for “\1”."),
            (r"^已恢复为新版本 (\d+)。$", r"Restored as revision \1."),
            (r"^预览失败：.*$", "Preview failed. See the job log for details."),
            (r"^(.+) 已进入后台导出队列。$", r"\1 was queued for background export."),
            (
                r"^已冻结术语版本 (\d+)，共 (\d+) 条。$",
                r"Frozen glossary revision \1 with \2 terms.",
            ),
            (
                r"^术语已保存，并修改 (\d+) 个已有译文段落。$",
                r"The term was saved and applied to \1 translated segments.",
            ),
            (r"^术语已保存，影响 (\d+) 个段落。$", r"The term was saved and affects \1 segments."),
            (r"^(.+) 连接正常.*$", r"\1 connected successfully."),
        )
        for pattern, replacement in patterns:
            if re.match(pattern, text):
                return re.sub(pattern, replacement, text)
        if re.search(r"[\u3400-\u9fff]", text):
            return "FolioCross updated the job. See its current status and log for details."
        return text

    @Slot(str)
    def setLanguage(self, language: str) -> None:
        normalized = "en" if language == "en" else "zh-CN"
        if normalized == self._language:
            return
        self._language = normalized
        self.service.repository.set_setting("ui_language", normalized)
        self.languageChanged.emit()
        for job in self._jobs:
            job["display_message"] = self._job_display_message(job)
        if self._selected:
            self._selected["display_message"] = self._job_display_message(self._selected)
        for step in self._steps:
            step["display_message"] = self.localizeText(step.get("message", ""))
        for event in self._events:
            event["display_payload"] = self._event_display_payload(event["payload"])
        self.jobsChanged.emit()
        self.detailsChanged.emit()

    @Slot(float)
    def setUiScale(self, scale: float) -> None:
        normalized = min(1.5, max(0.8, float(scale)))
        if normalized == self._ui_scale:
            return
        self._ui_scale = normalized
        self.service.repository.set_setting("ui_scale", normalized)
        self.scaleChanged.emit()

    @Slot(bool)
    def setDarkMode(self, enabled: bool) -> None:
        normalized = bool(enabled)
        if normalized == self._dark_mode:
            return
        self._dark_mode = normalized
        self.service.repository.set_setting("dark_mode", normalized)
        self.themeChanged.emit()

    @Slot()
    def refresh(self) -> None:
        self._publish_jobs(self._job_summaries(refresh_covers=True))
        if self._selected:
            self.selectJob(self._selected["id"])

    def _job_summaries(self, *, refresh_covers: bool = False) -> list[dict[str, Any]]:
        jobs = self.service.repository.list_jobs()
        operations = {
            operation["job_id"]: operation
            for operation in self.service.repository.background_operations("queued", "running")
        }
        if refresh_covers:
            self._cover_urls.clear()
        for job in jobs:
            job.pop("glossary_snapshot", None)
            if job["id"] not in self._cover_urls:
                cover = next(
                    (
                        artifact
                        for artifact in self.service.repository.list_artifacts(job["id"])
                        if artifact["kind"] == "cover"
                    ),
                    None,
                )
                self._cover_urls[job["id"]] = (
                    Path(cover["path"]).resolve().as_uri() if cover else ""
                )
            job["cover_url"] = self._cover_urls[job["id"]]
            job["background_operation"] = operations.get(job["id"], {})
            job["display_message"] = self._job_display_message(job)
        return jobs

    def _publish_jobs(self, jobs: list[dict[str, Any]]) -> None:
        self._jobs = jobs
        current_statuses = {job["id"]: job["status"] for job in self._jobs}
        if self._refresh_initialized:
            for job_id, status in current_statuses.items():
                previous = self._job_statuses.get(job_id)
                if previous == status:
                    continue
                if status == "completed":
                    self.workerEvent.emit("job.completed", json.dumps({"job_id": job_id}))
                elif status == "failed":
                    self.workerEvent.emit("job.failed", json.dumps({"job_id": job_id}))
        self._job_statuses = current_statuses
        self._refresh_initialized = True
        self.jobsChanged.emit()

    def _poll_jobs(self) -> None:
        selected_id = str(self._selected.get("id") or "")
        previous = (
            self._selected.get("status"),
            self._selected.get("stage"),
            self._selected.get("completed_segments"),
        )
        jobs = self._job_summaries()
        self._publish_jobs(jobs)
        self._poll_events()
        if not selected_id:
            return
        current = next((job for job in jobs if job["id"] == selected_id), None)
        if current is None:
            return
        changed = (current["status"], current["stage"], current["completed_segments"])
        if previous[:2] != changed[:2] and current["status"] in {
            "completed",
            "failed",
            "paused",
            "cancelled",
            "interrupted",
            "ready",
        }:
            self.selectJob(selected_id)
            return
        self._selected.update(current)
        if previous != changed:
            self.detailsChanged.emit()

    def _poll_events(self) -> None:
        events = self.service.repository.events_after(self._last_event_sequence)
        if not events:
            return
        self._last_event_sequence = int(events[-1]["seq"])
        selected_id = str(self._selected.get("id") or "")
        selected_events = [event for event in events if event.get("job_id") == selected_id]
        if selected_events:
            for event in selected_events:
                event["display_payload"] = self._event_display_payload(event["payload"])
            self._events.extend(selected_events)
            self._events = self._events[-300:]
            self.detailsChanged.emit()
        for event in events:
            if event["event_type"] in {"warning.raised", "operation.failed"}:
                self.workerEvent.emit(
                    event["event_type"], json.dumps(event["payload"], ensure_ascii=False)
                )

    def _event_display_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        if isinstance(result.get("message"), str):
            result["message"] = self.localizeText(result["message"])
        return result

    @staticmethod
    def _segments_for_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            row["source_display_text"] = strip_protected_markers(row.get("source_text", ""))
            row["target_display_text"] = strip_protected_markers(row.get("target_text", ""))
        return rows

    @Slot(str)
    def selectJob(self, job_id: str) -> None:
        try:
            changed_job = job_id != self._selected.get("id")
            self._selected = self.service.repository.get_job(job_id)
            self._selected.pop("glossary_snapshot", None)
            operation = self.service.repository.active_background_operation(job_id)
            self._selected["background_operation"] = operation or {}
            self._selected["display_message"] = self._job_display_message(self._selected)
            self._chapters = self.service.repository.chapters_for_job(job_id)
            if changed_job:
                self._glossary_query = ""
            self._glossary, self._glossary_total = self.service.repository.glossary_page(
                job_id,
                query=self._glossary_query,
                limit=self._glossary_page_size,
            )
            self._issues = self.service.repository.list_issues(job_id)
            self._usage = self.service.repository.usage_summary(job_id)
            self._artifacts = self.service.repository.list_artifacts(job_id)
            self._events = self.service.repository.list_events(job_id)
            for event in self._events:
                event["display_payload"] = self._event_display_payload(event["payload"])
            self._steps = self.service.repository.job_steps(job_id)
            for step in self._steps:
                step["display_message"] = self.localizeText(step.get("message", ""))
            self.service.repository.set_setting("last_job_id", job_id)
            if self._chapters:
                preferred = str(
                    self.service.repository.get_setting(f"last_chapter:{job_id}", "") or ""
                )
                chapter = next(
                    (item for item in self._chapters if item["id"] == preferred),
                    self._chapters[0],
                )
                self._selected_chapter_id = chapter["id"]
                self._segments = self._segments_for_display(
                    self.service.repository.segments_for_chapter(chapter["id"])
                )
            else:
                self._selected_chapter_id = ""
                self._segments = []
            self.detailsChanged.emit()
        except FolioCrossError as error:
            self.message.emit("error", error.localized(self._language))

    @Slot(str)
    def searchGlossary(self, query: str) -> None:
        self._glossary_query = query.strip()
        if not self._selected:
            self._glossary = []
            self._glossary_total = 0
        else:
            self._glossary, self._glossary_total = self.service.repository.glossary_page(
                self._selected["id"],
                query=self._glossary_query,
                limit=self._glossary_page_size,
            )
        self.detailsChanged.emit()

    @Slot()
    def loadMoreGlossary(self) -> None:
        if not self._selected or len(self._glossary) >= self._glossary_total:
            return
        rows, total = self.service.repository.glossary_page(
            self._selected["id"],
            query=self._glossary_query,
            offset=len(self._glossary),
            limit=self._glossary_page_size,
        )
        self._glossary.extend(rows)
        self._glossary_total = total
        self.detailsChanged.emit()

    @Slot(str)
    def selectChapter(self, chapter_id: str) -> None:
        self._segments = self._segments_for_display(
            self.service.repository.segments_for_chapter(chapter_id)
        )
        self._selected_chapter_id = chapter_id
        if self._selected:
            self.service.repository.set_setting(f"last_chapter:{self._selected['id']}", chapter_id)
        self.detailsChanged.emit()

    @Slot(str, result=int)
    def detailTab(self, job_id: str) -> int:
        return int(self.service.repository.get_setting(f"detail_tab:{job_id}", 0) or 0)

    @Slot(str, int)
    def saveDetailTab(self, job_id: str, index: int) -> None:
        if job_id:
            self.service.repository.set_setting(f"detail_tab:{job_id}", max(0, index))

    @Slot(str, str, result=float)
    def editorPosition(self, job_id: str, chapter_id: str) -> float:
        return float(
            self.service.repository.get_setting(f"editor_position:{job_id}:{chapter_id}", 0.0)
            or 0.0
        )

    @Slot(str, str, float)
    def saveEditorPosition(self, job_id: str, chapter_id: str, position: float) -> None:
        if job_id and chapter_id:
            self.service.repository.set_setting(
                f"editor_position:{job_id}:{chapter_id}", max(0.0, position)
            )

    @Slot(str)
    def importBook(self, url_or_path: str) -> None:
        path = self._local_path(url_or_path)
        if not path:
            return
        process = QProcess(self)
        key = f"import:{id(process)}"
        self._processes[key] = process
        self._set_busy(True)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-m",
                "foliocross.desktop.import_worker",
                "--workspace",
                str(self.workspace.root),
                "--path",
                path,
            ]
        )

        def finished() -> None:
            raw = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
            self._processes.pop(key, None)
            self._set_busy(bool(self._processes))
            try:
                result = json.loads(raw.splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                result = {"ok": False, "error": {"message": raw or "导入进程没有返回结果"}}
            if result.get("ok"):
                self.refresh()
                self.selectJob(result["job_id"])
                self.importFinished.emit(result["job_id"])
                action = "已打开现有任务" if result.get("reused") else "已导入"
                self.message.emit("success", f"{action}《{result.get('title', '')}》")
            else:
                self.message.emit("error", result.get("error", {}).get("message", "导入失败"))
            process.deleteLater()

        process.finished.connect(finished)
        process.start()

    @Slot(str)
    def startJob(self, job_id: str) -> None:
        try:
            operation = self.service.repository.enqueue_background_operation(job_id, "run")
            self.service.control_job(job_id, "run")
            if operation["status"] == "queued":
                active_limit = int(self.service.repository.get_setting("active_task_limit", 1) or 1)
                self.service.repository.update_job(
                    job_id,
                    status="queued",
                    message=f"已排队；当前最多同时运行 {max(1, active_limit)} 本书",
                )
            self._scheduler_starter(self.workspace)
            self.refresh()
            self.message.emit("info", "任务已进入后台队列，关闭界面后仍会继续。")
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str)
    def startPreparation(self, job_id: str) -> None:
        try:
            operation = self.service.repository.enqueue_background_operation(job_id, "prepare")
            self.service.control_job(job_id, "run")
            if operation["status"] == "queued":
                active_limit = int(self.service.repository.get_setting("active_task_limit", 1) or 1)
                self.service.repository.update_job(
                    job_id,
                    status="queued",
                    message=f"译前准备已排队；当前最多同时运行 {max(1, active_limit)} 本书",
                )
            self._scheduler_starter(self.workspace)
            self.refresh()
            self.message.emit("info", "译前准备已进入后台队列。")
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    def _queue_background_action(
        self,
        *,
        job_id: str,
        action: str,
        arguments: dict[str, Any] | None,
        success_message: str,
    ) -> None:
        try:
            self.service.repository.enqueue_background_operation(job_id, action, arguments)
            self._scheduler_starter(self.workspace)
            self.refresh()
            self.message.emit("info", success_message)
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    def _queue_legacy_job_if_needed(self, job_id: str) -> None:
        if not self.service.repository.active_background_operation(job_id):
            self.service.repository.enqueue_background_operation(job_id, "run")

    def _pause_or_cancel_queued_operation(self, job_id: str, *, cancel: bool) -> bool:
        stopped = self.service.repository.cancel_queued_background_operation(job_id)
        if not stopped:
            return False
        if cancel:
            self.service.repository.update_job(
                job_id,
                status="cancelled",
                stage="cancelled",
                message="排队任务已取消",
                finished=True,
            )
        else:
            self.service.repository.update_job(job_id, status="paused", message="已从后台队列暂停")
        return True

    @Slot(str, str, str, bool, str, str, int, str, str, str, result=bool)
    def configureJob(
        self,
        job_id: str,
        source_lang: str,
        output_format: str,
        bilingual: bool,
        soft_budget_text: str,
        hard_budget_text: str,
        max_concurrency: int,
        rpm_text: str,
        tpm_text: str,
        action: str,
    ) -> bool:
        try:
            soft_budget = float(soft_budget_text) if soft_budget_text.strip() else None
            hard_budget = float(hard_budget_text) if hard_budget_text.strip() else None
            rpm = int(rpm_text) if rpm_text.strip() else None
            tpm = int(tpm_text) if tpm_text.strip() else None
            if soft_budget is not None and soft_budget <= 0:
                raise ValueError("费用提醒值必须大于 0。")
            if hard_budget is not None and hard_budget < 0:
                raise ValueError("费用上限不能为负数。")
            if soft_budget is not None and hard_budget is not None and soft_budget > hard_budget:
                raise ValueError("费用提醒值不能高于硬预算上限。")
            if rpm is not None and rpm <= 0:
                raise ValueError("RPM 必须大于 0。")
            if tpm is not None and tpm <= 0:
                raise ValueError("TPM 必须大于 0。")
            self.service.configure_job(
                job_id,
                source_lang=source_lang,
                output_format=output_format,
                bilingual=bilingual,
                soft_budget=soft_budget,
                hard_budget=hard_budget,
                max_concurrency=max_concurrency,
                requests_per_minute=rpm,
                tokens_per_minute=tpm,
            )
            self.selectJob(job_id)
            if action == "prepare":
                self.startPreparation(job_id)
            elif action == "start":
                self.startJob(job_id)
            else:
                self.message.emit("success", "翻译设置已保存。")
            return True
        except (FolioCrossError, ValueError) as error:
            self.message.emit("error", getattr(error, "message", str(error)))
            return False

    @Slot(str)
    def pauseJob(self, job_id: str) -> None:
        self.service.control_job(job_id, "pause")
        self._pause_or_cancel_queued_operation(job_id, cancel=False)
        self.refresh()
        self.message.emit("info", "将在当前请求结束后暂停。")

    @Slot(str)
    def cancelJob(self, job_id: str) -> None:
        self.service.control_job(job_id, "cancel")
        self._pause_or_cancel_queued_operation(job_id, cancel=True)
        self.refresh()
        self.message.emit("info", "任务将停止，已经完成的译文会保留。")

    @Slot(str)
    def archiveJob(self, job_id: str) -> None:
        try:
            self.service.archive_job(job_id)
            self._selected = {}
            self._chapters = []
            self._segments = []
            self._selected_chapter_id = ""
            self._glossary = []
            self._glossary_total = 0
            self._issues = []
            self._usage = {}
            self._artifacts = []
            self._events = []
            self._steps = []
            self.detailsChanged.emit()
            self.refresh()
            self.message.emit("success", "任务已归档，书籍和所有译文仍保留在工作区。")
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str)
    def forceStopJob(self, job_id: str) -> None:
        try:
            self.service.control_job(job_id, "pause")
            requested = self.service.repository.request_background_operation_cancel(job_id)
            if requested:
                self._scheduler_starter(self.workspace)
                self.message.emit("warning", "正在停止 Worker；在途请求可能已产生费用。")
            elif self._pause_or_cancel_queued_operation(job_id, cancel=False):
                self.message.emit("info", "排队中的后台操作已停止。")
            else:
                self.message.emit("info", "这本书当前没有正在运行的 Worker。")
            self.refresh()
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str, str, int, result=int)
    def saveSegment(self, segment_id: str, text: str, expected_version: int) -> int:
        try:
            current = self.service.repository.segment(segment_id)
            internal_text = restore_protected_markers(
                current["source_text"], current["target_text"], text, current["markers"]
            )
            result = self.service.edit_segment(
                segment_id, internal_text, expected_version=expected_version
            )
            for segment in self._segments:
                if segment["id"] == segment_id:
                    segment["target_text"] = internal_text
                    segment["target_display_text"] = strip_protected_markers(internal_text)
                    segment["version"] = result["version"]
                    segment["locked"] = True
                    break
            return int(result["version"])
        except FolioCrossError as error:
            self.message.emit("error", error.message)
            return -1

    @Slot(str)
    def segmentHistory(self, segment_id: str) -> None:
        current = self.service.repository.segment(segment_id)["target_text"]
        rows = self.service.repository.segment_revisions(segment_id)
        for row in rows:
            row["current_text"] = current
            row["is_current"] = row["text"] == current
            row["display_text"] = strip_protected_markers(row["text"])
            row["current_display_text"] = strip_protected_markers(current)
        self.historyReady.emit(rows)

    @Slot(str)
    def restoreRevision(self, revision_id: str) -> None:
        try:
            result = self.service.restore_revision(revision_id)
            self.message.emit("success", f"已恢复为新版本 {result['version']}。")
            if self._selected:
                self.selectJob(self._selected["id"])
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str, str, str)
    @Slot(str, str, str, bool)
    def saveGlossary(
        self, job_id: str, source: str, target: str, apply_existing: bool = False
    ) -> None:
        try:
            result = self.service.update_glossary(
                job_id, source, target, apply_existing=apply_existing
            )
            if apply_existing:
                message = f"术语已保存，并修改 {result['applied_segments']} 个已有译文段落。"
            else:
                message = f"术语已保存，影响 {result['affected_segments']} 个段落。"
            self.message.emit("success", message)
            self.selectJob(job_id)
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str, str)
    def resolveIssue(self, issue_id: str, status: str) -> None:
        try:
            self.service.repository.resolve_issue(issue_id, status)
            if self._selected:
                self.selectJob(self._selected["id"])
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str)
    @Slot(str, str)
    def acceptIssue(self, issue_id: str, suggestion: str | None = None) -> None:
        try:
            self.service.apply_issue_suggestion(issue_id, suggestion)
            self.message.emit("success", "修改建议已作为人工锁定版本应用。")
            if self._selected:
                self.selectJob(self._selected["id"])
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str, str)
    def showAffectedSegments(self, job_id: str, source: str) -> None:
        rows = self.service.repository.affected_segments(job_id, source)
        self.affectedSegmentsReady.emit(self._segments_for_display(rows))

    @Slot(str)
    def refreshGlossarySnapshot(self, job_id: str) -> None:
        try:
            result = self.service.refresh_glossary_snapshot(job_id)
            self.message.emit(
                "success", f"已冻结术语版本 {result['version']}，共 {len(result['terms'])} 条。"
            )
            self.selectJob(job_id)
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str, result="QVariantMap")
    def reviewEstimate(self, job_id: str):
        try:
            return self.service.estimate_deep_review(job_id)
        except FolioCrossError as error:
            self.message.emit("error", error.message)
            return {"ok": False, "error": error.message}

    @Slot(str)
    def startDeepReview(self, job_id: str) -> None:
        self._queue_background_action(
            job_id=job_id,
            action="review",
            arguments={},
            success_message="深度审校已进入后台队列，完成后结果会出现在质量列表。",
        )

    @Slot(str, str, str)
    def retranslateSegment(self, job_id: str, segment_id: str, instruction: str) -> None:
        self._queue_background_action(
            job_id=job_id,
            action="retranslate",
            arguments={"segment_id": segment_id, "instruction": instruction},
            success_message="该段重译已进入后台队列，完成后会保存到修改历史。",
        )

    @Slot(str, str)
    def reExport(self, job_id: str, format_name: str) -> None:
        self._queue_background_action(
            job_id=job_id,
            action="export",
            arguments={"format_name": format_name},
            success_message=f"{format_name.upper()} 已进入后台导出队列。",
        )

    @Slot(str)
    def openPath(self, path: str) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def openContainingFolder(self, path: str) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve().parent)))

    @Slot(str, result=str)
    def previewArtifact(self, path: str) -> str:
        source = Path(path)
        try:
            suffix = source.suffix.lower()
            if suffix in {".txt", ".md", ".markdown"}:
                text = source.read_text(encoding="utf-8-sig")
            elif suffix in {".html", ".htm"}:
                text = BeautifulSoup(source.read_bytes(), "lxml").get_text("\n", strip=True)
            elif suffix == ".docx":
                document = Document(source)
                values = [paragraph.text for paragraph in document.paragraphs]
                values.extend(
                    paragraph.text
                    for table in document.tables
                    for row in table.rows
                    for cell in row.cells
                    for paragraph in cell.paragraphs
                )
                text = "\n\n".join(value for value in values if value.strip())
            elif suffix == ".epub":
                pieces: list[str] = []
                with zipfile.ZipFile(source) as archive:
                    for name in archive.namelist():
                        if Path(name).suffix.lower() not in {".xhtml", ".html", ".htm"}:
                            continue
                        visible = BeautifulSoup(archive.read(name), "lxml").get_text(
                            "\n", strip=True
                        )
                        if visible:
                            pieces.append(visible)
                        if sum(len(item) for item in pieces) >= 40_000:
                            break
                text = "\n\n".join(pieces)
            else:
                raise FolioCrossError("preview_unsupported", "这种文件暂不支持应用内预览。")
            return text[:40_000]
        except (OSError, zipfile.BadZipFile, ValueError) as error:
            self.message.emit("error", f"预览失败：{error}")
            return ""

    @Slot(str, str)
    def saveApiKey(self, profile_id: str, api_key: str) -> None:
        try:
            self.service.save_api_key(profile_id, api_key)
            self.message.emit("success", "API Key 已保存到 Windows 凭据管理器。")
        except Exception as error:
            self.message.emit("error", str(error))

    @Slot(str, result=bool)
    def completeFirstRun(self, api_key: str) -> bool:
        try:
            if api_key.strip():
                self.service.save_api_key("deepseek-default", api_key.strip())
            self.service.repository.set_setting("first_run_complete", True)
            self.message.emit("success", "首次启动设置已完成。")
            return True
        except Exception as error:
            self.message.emit("error", str(error))
            return False

    @Slot()
    def testModelConnection(self) -> None:
        key = "model-connection"
        if key in self._processes:
            return
        process = QProcess(self)
        self._processes[key] = process
        self._set_busy(True)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-m",
                "foliocross.cli",
                "--workspace",
                str(self.workspace.root),
                "doctor",
                "--live-model",
                "--json",
            ]
        )

        def finished(exit_code: int) -> None:
            output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
            error = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
            self._processes.pop(key, None)
            self._set_busy(bool(self._processes))
            if exit_code == 0:
                try:
                    result = json.loads(output)
                    check = result["model_connection"]
                    cost = check.get("cost")
                    cost_text = "" if cost is None else f"，本次约 {cost:.6f} {check['currency']}"
                    self.message.emit("success", f"{check['model']} 连接正常{cost_text}。")
                except (KeyError, TypeError, json.JSONDecodeError):
                    self.message.emit("error", "连接检查返回了无法识别的结果。")
            else:
                self.message.emit(
                    "error", self._process_error_message(error or output or "模型连接失败")
                )
            process.deleteLater()

        process.finished.connect(finished)
        process.start()

    @Slot(str, str, str, str, str, str, str, str, str)
    def saveModelSettings(
        self,
        provider: str,
        base_url: str,
        model: str,
        input_price: str,
        cached_input_price: str,
        output_price: str,
        currency: str,
        effective_date: str,
        price_source: str,
    ) -> None:
        try:
            if not model.strip():
                raise ValueError("模型名称不能为空。")
            self.service.save_model_profile(
                {
                    "provider": provider,
                    "base_url": base_url,
                    "model": model,
                    "input_price": input_price,
                    "cached_input_price": cached_input_price,
                    "output_price": output_price,
                    "currency": currency,
                    "effective_date": effective_date,
                    "price_source": price_source,
                }
            )
            self.message.emit("success", "模型与价格设置已保存，将用于之后新建的任务。")
        except (FolioCrossError, ValueError) as error:
            self.message.emit("error", getattr(error, "message", str(error)))

    @Slot(str)
    def setCalibrePath(self, path: str) -> None:
        self.service.repository.set_setting("calibre_path", self._local_path(path))
        self.message.emit("success", "Calibre 路径已保存。")

    @Slot(int)
    def saveActiveTaskLimit(self, value: int) -> None:
        self.service.repository.set_setting("active_task_limit", max(1, min(4, value)))
        self.message.emit("success", "同时运行书籍数已保存。")
        self._start_next_queued()

    @Slot(result="QVariantMap")
    def doctor(self):
        return self.service.doctor()

    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit()

    def _start_next_queued(self) -> None:
        queued = [
            job
            for job in self.service.repository.list_jobs()
            if job["status"] == "queued" and job["desired_state"] == "run"
        ]
        for job in queued:
            self._queue_legacy_job_if_needed(job["id"])
        if queued or self.service.repository.background_operations("queued", "running"):
            self._scheduler_starter(self.workspace)

    def _job_display_message(self, job: dict[str, Any]) -> str:
        if self._language != "en":
            return str(job.get("current_message") or "")
        status = str(job.get("status") or "")
        if status == "failed":
            return localized_error(job.get("error_code"), "en", str(job.get("error_message") or ""))
        operation = job.get("background_operation") or {}
        if operation.get("status") == "queued":
            action = operation.get("action", "run")
            labels = {
                "run": "Translation is queued and will start automatically.",
                "prepare": "Book preparation is queued and will start automatically.",
                "review": "Deep review is queued and will start automatically.",
                "retranslate": "Segment retranslation is queued and will start automatically.",
                "export": "Export is queued and will start automatically.",
            }
            return labels.get(action, "The background operation is queued.")
        if operation.get("status") == "running":
            action = operation.get("action", "run")
            labels = {
                "run": "Translation is running in the background.",
                "prepare": "Book preparation is running in the background.",
                "review": "Deep review is running in the background.",
                "retranslate": "Segment retranslation is running in the background.",
                "export": "Export is running in the background.",
            }
            return labels.get(action, "The background operation is running.")
        messages = {
            "preparing": "Analyzing the book and preparing its frozen glossary.",
            "translating": "Translating the book in the background.",
            "quality_check": "Checking translation quality.",
            "ready": "Translation is complete and ready to export.",
            "exporting": "Generating the translated book.",
            "completed": "Translation and export are complete.",
            "paused": "The job is paused at a safe checkpoint.",
            "interrupted": "The previous run was interrupted. Resume to continue from saved work.",
            "cancelled": "The job was cancelled. Completed work remains available.",
            "queued": "The job is queued and will start automatically.",
        }
        if status == "paused" and job.get("stage") == "prepared":
            return "Book preparation is complete. Review the glossary before continuing."
        if status == "paused" and job.get("stage") == "migrated":
            return "The Wenyi state was imported. Review it before resuming."
        return messages.get(status, "Imported and waiting to start.")

    @staticmethod
    def _local_path(value: str) -> str:
        url = QUrl(value)
        return url.toLocalFile() if url.isLocalFile() else value

    @staticmethod
    def _process_error_message(raw: str) -> str:
        line = raw.strip().splitlines()[-1] if raw.strip() else "操作失败"
        try:
            payload = json.loads(line)
            return str(payload.get("error", {}).get("message") or line)
        except (AttributeError, json.JSONDecodeError):
            return line
