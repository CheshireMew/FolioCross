"""QML-facing controller. Heavy operations always run in child processes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QProcess, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ..application.service import FolioCrossService
from ..errors import FolioCrossError
from ..infrastructure.workspace import Workspace

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


class DesktopController(QObject):
    jobsChanged = Signal()
    detailsChanged = Signal()
    busyChanged = Signal()
    message = Signal(str, str)
    importFinished = Signal(str)
    workerEvent = Signal(str, str)
    historyReady = Signal("QVariantList")

    def __init__(self, workspace: Workspace) -> None:
        super().__init__()
        self.workspace = workspace
        self.service = FolioCrossService(workspace)
        self._jobs: list[dict[str, Any]] = []
        self._selected: dict[str, Any] = {}
        self._chapters: list[dict[str, Any]] = []
        self._segments: list[dict[str, Any]] = []
        self._glossary: list[dict[str, Any]] = []
        self._issues: list[dict[str, Any]] = []
        self._usage: dict[str, Any] = {}
        self._artifacts: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._steps: list[dict[str, Any]] = []
        self._busy = False
        self._language = self.service.repository.get_setting("ui_language", "zh-CN")
        self._processes: dict[str, QProcess] = {}
        self.refresh()

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

    @Property("QVariantList", notify=detailsChanged)
    def glossary(self):
        return self._glossary

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

    @Slot(str, result=str)
    def t(self, key: str) -> str:
        return TEXTS.get(self._language, TEXTS["zh-CN"]).get(key, key)

    @Slot()
    def refresh(self) -> None:
        self._jobs = self.service.repository.list_jobs()
        self.jobsChanged.emit()
        if self._selected:
            self.selectJob(self._selected["id"])

    @Slot(str)
    def selectJob(self, job_id: str) -> None:
        try:
            self._selected = self.service.repository.get_job(job_id)
            self._chapters = self.service.repository.chapters_for_job(job_id)
            self._glossary = self.service.repository.list_glossary(job_id)
            self._issues = self.service.repository.list_issues(job_id)
            self._usage = self.service.repository.usage_summary(job_id)
            self._artifacts = self.service.repository.list_artifacts(job_id)
            self._events = self.service.repository.list_events(job_id)
            self._steps = self.service.repository.job_steps(job_id)
            if self._chapters:
                self._segments = self.service.repository.segments_for_chapter(
                    self._chapters[0]["id"]
                )
            else:
                self._segments = []
            self.detailsChanged.emit()
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str)
    def selectChapter(self, chapter_id: str) -> None:
        self._segments = self.service.repository.segments_for_chapter(chapter_id)
        self.detailsChanged.emit()

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
        if job_id in self._processes:
            return
        active_limit = int(self.service.repository.get_setting("active_task_limit", 1) or 1)
        active_jobs = [key for key in self._processes if ":" not in key]
        if len(active_jobs) >= max(1, active_limit):
            self.message.emit(
                "warning", f"当前最多同时运行 {max(1, active_limit)} 本书，可在设置中调整。"
            )
            return
        self.service.control_job(job_id, "run")
        process = QProcess(self)
        self._processes[job_id] = process
        self._set_busy(True)
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-m",
                "foliocross.worker",
                "--workspace",
                str(self.workspace.root),
                "--job",
                job_id,
            ]
        )

        def output_ready() -> None:
            while process.canReadLine():
                line = bytes(process.readLine()).decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    self.workerEvent.emit(
                        str(event.get("type", "event")),
                        json.dumps(event.get("payload", {}), ensure_ascii=False),
                    )
                except json.JSONDecodeError:
                    self.workerEvent.emit("log", line)
            self.refresh()

        def finished() -> None:
            stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            self._processes.pop(job_id, None)
            self._set_busy(bool(self._processes))
            self.refresh()
            if stderr:
                self.message.emit("error", stderr.splitlines()[-1])
            process.deleteLater()

        process.readyReadStandardOutput.connect(output_ready)
        process.finished.connect(finished)
        process.start()

    @Slot(str)
    def startPreparation(self, job_id: str) -> None:
        if job_id in self._processes:
            return
        active_limit = int(self.service.repository.get_setting("active_task_limit", 1) or 1)
        active_jobs = [key for key in self._processes if ":" not in key]
        if len(active_jobs) >= max(1, active_limit):
            self.message.emit(
                "warning", f"当前最多同时运行 {max(1, active_limit)} 本书，可在设置中调整。"
            )
            return
        self._start_worker_action(
            key=job_id,
            arguments=["--job", job_id, "--prepare-only"],
            success_message="译前准备完成，可以检查术语后继续翻译。",
        )

    @Slot(str, str, str, bool, str, str, str)
    def configureJob(
        self,
        job_id: str,
        source_lang: str,
        output_format: str,
        bilingual: bool,
        soft_budget_text: str,
        hard_budget_text: str,
        action: str,
    ) -> None:
        try:
            soft_budget = float(soft_budget_text) if soft_budget_text.strip() else None
            hard_budget = float(hard_budget_text) if hard_budget_text.strip() else None
            if soft_budget is not None and soft_budget <= 0:
                raise ValueError("费用提醒值必须大于 0。")
            if hard_budget is not None and hard_budget <= 0:
                raise ValueError("费用上限必须大于 0。")
            if soft_budget is not None and hard_budget is not None and soft_budget > hard_budget:
                raise ValueError("费用提醒值不能高于硬预算上限。")
            self.service.configure_job(
                job_id,
                source_lang=source_lang,
                output_format=output_format,
                bilingual=bilingual,
                soft_budget=soft_budget,
                hard_budget=hard_budget,
            )
            self.selectJob(job_id)
            if action == "prepare":
                self.startPreparation(job_id)
            elif action == "start":
                self.startJob(job_id)
            else:
                self.message.emit("success", "翻译设置已保存。")
        except (FolioCrossError, ValueError) as error:
            self.message.emit("error", getattr(error, "message", str(error)))

    @Slot(str)
    def pauseJob(self, job_id: str) -> None:
        self.service.control_job(job_id, "pause")
        self.message.emit("info", "将在当前请求结束后暂停。")

    @Slot(str)
    def cancelJob(self, job_id: str) -> None:
        self.service.control_job(job_id, "cancel")
        self.message.emit("info", "任务将停止，已经完成的译文会保留。")

    @Slot(str)
    def archiveJob(self, job_id: str) -> None:
        try:
            self.service.archive_job(job_id)
            self._selected = {}
            self._chapters = []
            self._segments = []
            self._glossary = []
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
        process = self._processes.get(job_id)
        if process:
            self.service.control_job(job_id, "pause")
            process.terminate()
            self.service.repository.update_job(
                job_id, status="interrupted", message="Worker 被立即停止，可以继续运行"
            )
            self.message.emit("warning", "Worker 已停止；在途请求可能已产生费用。")

    @Slot(str, str, int)
    def saveSegment(self, segment_id: str, text: str, expected_version: int) -> None:
        try:
            self.service.edit_segment(segment_id, text, expected_version=expected_version)
            if self._selected:
                self.selectJob(self._selected["id"])
        except FolioCrossError as error:
            self.message.emit("error", error.message)

    @Slot(str)
    def segmentHistory(self, segment_id: str) -> None:
        self.historyReady.emit(self.service.repository.segment_revisions(segment_id))

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
    def acceptIssue(self, issue_id: str) -> None:
        try:
            self.service.apply_issue_suggestion(issue_id)
            self.message.emit("success", "修改建议已作为人工锁定版本应用。")
            if self._selected:
                self.selectJob(self._selected["id"])
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
        self._start_worker_action(
            key=f"review:{job_id}",
            arguments=["--job", job_id, "--review"],
            success_message="深度审校完成，结果已进入质量问题列表。",
        )

    @Slot(str, str, str)
    def retranslateSegment(self, job_id: str, segment_id: str, instruction: str) -> None:
        self._start_worker_action(
            key=f"retranslate:{segment_id}",
            arguments=[
                "--job",
                job_id,
                "--retranslate",
                segment_id,
                "--instruction",
                instruction,
            ],
            success_message="该段重译完成，并已保存到修改历史。",
        )

    @Slot(str, str)
    def reExport(self, job_id: str, format_name: str) -> None:
        self._start_worker_action(
            key=f"export:{job_id}",
            arguments=["--job", job_id, "--export-format", format_name],
            success_message=f"{format_name.upper()} 已重新生成。",
        )

    @Slot(str)
    def openPath(self, path: str) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def openContainingFolder(self, path: str) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve().parent)))

    @Slot(str, str)
    def saveApiKey(self, profile_id: str, api_key: str) -> None:
        try:
            self.service.save_api_key(profile_id, api_key)
            self.message.emit("success", "API Key 已保存到 Windows 凭据管理器。")
        except Exception as error:
            self.message.emit("error", str(error))

    @Slot(str)
    def completeFirstRun(self, api_key: str) -> None:
        try:
            if api_key.strip():
                self.service.save_api_key("deepseek-default", api_key.strip())
            self.service.repository.set_setting("first_run_complete", True)
            self.message.emit("success", "首次启动设置已完成。")
        except Exception as error:
            self.message.emit("error", str(error))

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
                self.message.emit("error", (error or output or "模型连接失败").splitlines()[-1])
            process.deleteLater()

        process.finished.connect(finished)
        process.start()

    @Slot(str, str, str, str, str, str, str, str)
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

    @Slot(result="QVariantMap")
    def doctor(self):
        return self.service.doctor()

    def _start_worker_action(self, *, key: str, arguments: list[str], success_message: str) -> None:
        if key in self._processes:
            return
        process = QProcess(self)
        self._processes[key] = process
        self._set_busy(True)
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.setProgram(sys.executable)
        process.setArguments(
            ["-m", "foliocross.worker", "--workspace", str(self.workspace.root), *arguments]
        )

        def output_ready() -> None:
            while process.canReadLine():
                line = bytes(process.readLine()).decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    self.workerEvent.emit(
                        str(event.get("type", "event")),
                        json.dumps(event.get("payload", {}), ensure_ascii=False),
                    )
                except json.JSONDecodeError:
                    self.workerEvent.emit("log", line)
            self.refresh()

        def finished(exit_code: int) -> None:
            stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            self._processes.pop(key, None)
            self._set_busy(bool(self._processes))
            self.refresh()
            if exit_code == 0:
                self.message.emit("success", success_message)
            else:
                self.message.emit("error", stderr.splitlines()[-1] if stderr else "操作失败")
            process.deleteLater()

        process.readyReadStandardOutput.connect(output_ready)
        process.finished.connect(finished)
        process.start()

    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit()

    @staticmethod
    def _local_path(value: str) -> str:
        url = QUrl(value)
        return url.toLocalFile() if url.isLocalFile() else value
