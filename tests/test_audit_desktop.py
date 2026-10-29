import pytest

from foliocross.application.service import FolioCrossService
from foliocross.desktop.controller import DesktopController
from foliocross.domain.models import JobConfig, ModelProfile
from foliocross.worker.engine import WorkerEngine


@pytest.fixture
def controller_factory(qtbot, workspace):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    controllers = []

    def create(**kwargs):
        controller = DesktopController(workspace, **kwargs)
        controllers.append(controller)
        return controller

    yield create
    # Own the QObjects until their event callbacks have drained. Leaving Python
    # cyclic GC to dispose active timers can make successive Qt tests interfere.
    for controller in controllers:
        if isValid(controller):
            controller._poll_timer.stop()
            qtbot.waitUntil(lambda: not controller._processes, timeout=20_000)
            controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_background_retranslate_refreshes_without_status_change(
    qtbot, workspace, controller_factory, tmp_path
):
    source = tmp_path / "book.txt"
    source.write_text("Some text", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), JobConfig(profile=ModelProfile(provider="fake")))[
        "job_id"
    ]
    WorkerEngine(workspace).run(job_id, export_when_done=False)
    controller = controller_factory()
    controller.selectJob(job_id)
    segment = controller.segments[0]
    WorkerEngine(workspace).retranslate_segment(job_id, segment["id"], "Improve")
    controller._poll_jobs()
    assert controller.segments[0]["version"] == segment["version"] + 1


def test_export_review_and_external_cli_refresh_their_panels(
    qtbot, workspace, controller_factory, tmp_path, monkeypatch
):
    import json
    import subprocess
    import sys

    from foliocross.infrastructure.llm import FakeClient, ModelResponse, ModelUsage

    source = tmp_path / "panels.txt"
    source.write_text("Original paragraph", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), JobConfig(profile=ModelProfile(provider="fake")))[
        "job_id"
    ]
    worker = WorkerEngine(workspace)
    worker.run(job_id, export_when_done=False)
    controller = controller_factory()
    controller.selectJob(job_id)
    old_status = controller.selectedJob["status"]
    original = FakeClient.complete

    def review_result(self, **kwargs):
        payload = json.loads(kwargs["user"])
        if "review_segments" in payload:
            return ModelResponse(
                json.dumps(
                    {
                        "issues": [
                            {
                                "segment_id": controller.segments[0]["id"],
                                "message": "Review this sentence",
                                "suggestion": "Suggested",
                            }
                        ]
                    }
                ),
                ModelUsage(prompt_tokens=321, completion_tokens=22),
            )
        return original(self, **kwargs)

    monkeypatch.setattr(FakeClient, "complete", review_result)
    worker.deep_review(job_id)
    exported = worker.export_only(job_id, "txt")
    assert service.repository.get_job(job_id)["status"] == old_status
    controller._poll_jobs()
    assert any(issue["message"] == "Review this sentence" for issue in controller.issues)
    assert any(artifact["id"] == exported["artifact_id"] for artifact in controller.artifacts)
    assert any(row["stage"] == "deep_review" for row in controller.usage["by_stage_model"])
    edit = tmp_path / "edit.txt"
    edit.write_text("Edited by external CLI", encoding="utf-8")
    segment = controller.segments[0]
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "foliocross.cli",
            "--workspace",
            str(workspace.root),
            "segments",
            "edit",
            segment["id"],
            "--text-file",
            str(edit),
            "--expected-version",
            str(segment["version"]),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.returncode == 0, process.stderr
    controller._poll_jobs()
    assert controller.segments[0]["target_text"] == "Edited by external CLI"
    assert controller.segments[0]["locked"]


def test_refresh_preserves_draft_and_rejects_stale_save(
    qtbot, workspace, controller_factory, tmp_path
):
    source = tmp_path / "draft.txt"
    source.write_text("Original", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source))["job_id"]
    controller = controller_factory()
    controller.selectJob(job_id)
    segment = controller.segments[0]
    controller.setDraft(segment["id"], "My unsaved words", segment["version"])
    service.edit_segment(segment["id"], "External edit")
    controller._poll_jobs()
    shown = controller.segments[0]
    assert shown["target_display_text"] == "External edit"
    assert shown["edit_text"] == "My unsaved words"
    assert shown["edit_version"] == segment["version"]
    assert controller.saveSegment(segment["id"], shown["edit_text"], shown["edit_version"]) == -1
    controller.discardDraft(segment["id"])
    assert controller.segments[0]["edit_text"] == "External edit"


def test_preview_child_keeps_qt_event_loop_active(qtbot, workspace, controller_factory, tmp_path):
    from PySide6.QtCore import QTimer

    source = tmp_path / "large.html"
    source.write_text(
        "<html><body>" + "<p>A paragraph for preview.</p>" * 100_000 + "</body></html>",
        encoding="utf-8",
    )
    controller = controller_factory()
    results = []
    controller.artifactPreviewReady.connect(lambda path, text: results.append((path, text)))
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    assert controller.previewArtifact(str(source)) is None
    assert results == []
    qtbot.waitUntil(lambda: bool(results), timeout=20_000)
    timer.stop()
    assert len(ticks) >= 3
    assert len(results[0][1]) <= 40_000
    assert "A paragraph for preview." in results[0][1]


def test_preview_child_reports_failure_and_releases_busy_state(qtbot, controller_factory, tmp_path):
    controller = controller_factory()
    results, messages = [], []
    controller.artifactPreviewReady.connect(lambda path, text: results.append((path, text)))
    controller.message.connect(lambda level, text: messages.append((level, text)))
    missing = str(tmp_path / "missing.html")
    controller.previewArtifact(missing)
    qtbot.waitUntil(lambda: bool(results), timeout=10_000)
    assert results[0][0] == missing
    assert "预览失败" in results[0][1]
    assert any(level == "error" for level, _ in messages)
    assert not controller.busy


def test_review_estimate_child_returns_actual_result(
    qtbot, workspace, controller_factory, tmp_path
):
    source = tmp_path / "review.txt"
    source.write_text("Original", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source))["job_id"]
    controller = controller_factory()
    controller.selectJob(job_id)
    service.edit_segment(controller.segments[0]["id"], "Translation")
    results = []
    controller.reviewEstimateReady.connect(lambda job, result: results.append((job, result)))
    assert controller.reviewEstimate(job_id) is None
    qtbot.waitUntil(lambda: bool(results), timeout=10_000)
    assert results[0] == (job_id, service.estimate_deep_review(job_id))


def test_glossary_application_runs_through_durable_worker(
    qtbot, workspace, controller_factory, tmp_path
):
    from foliocross.worker.scheduler import run_scheduler

    source = tmp_path / "glossary.txt"
    source.write_text("Alice speaks.", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source))["job_id"]
    controller = controller_factory(scheduler_starter=lambda workspace: 0)
    controller.selectJob(job_id)
    segment = controller.segments[0]
    service.edit_segment(segment["id"], "OldName speaks.")
    service.repository.upsert_glossary_terms(job_id, [{"source": "Alice", "target": "OldName"}])
    controller.saveGlossary(job_id, "Alice", "NewName", True)
    assert service.repository.segment(segment["id"])["target_text"] == "OldName speaks."
    assert run_scheduler(workspace, poll_interval=0.02, idle_grace_seconds=0.05) == 0
    controller._poll_jobs()
    assert controller.segments[0]["target_text"] == "NewName speaks."
    assert controller.segments[0]["locked"]


def test_qml_consumes_async_preview_estimate_and_keeps_draft(
    qtbot, workspace, controller_factory, tmp_path
):
    from importlib.resources import files

    from PySide6.QtCore import QObject, QPointF, Qt, QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from shiboken6 import getCppPointer, wrapInstance
    from test_desktop_qml import _visual_child_for_segment

    source = tmp_path / "visible.txt"
    source.write_text("Original paragraph", encoding="utf-8")
    service = FolioCrossService(workspace)
    service.repository.set_setting("first_run_complete", True)
    job_id = service.import_book(str(source))["job_id"]
    controller = controller_factory()
    controller.selectJob(job_id)
    segment = controller.segments[0]
    service.edit_segment(segment["id"], "Initial translation")
    exported = service.export(job_id, "txt")
    controller._poll_jobs()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", controller)
    engine.load(QUrl.fromLocalFile(str(files("foliocross.desktop.qml").joinpath("Main.qml"))))
    root = engine.rootObjects()[0]
    qtbot.waitExposed(root)
    tabs = root.findChild(QObject, "detailTabs")
    tabs.setProperty("currentIndex", 1)
    segment_list = root.findChild(QObject, "segmentList")
    item = wrapInstance(getCppPointer(segment_list)[0], QQuickItem)

    def editor():
        return _visual_child_for_segment(item, "translationEditor", segment["id"])

    qtbot.waitUntil(lambda: editor() is not None)
    editor().forceActiveFocus()
    qtbot.waitUntil(lambda: editor().property("activeFocus"))
    editor().setProperty("text", "Unsaved draft")
    service.edit_segment(segment["id"], "External new version")
    controller._poll_jobs()
    qtbot.waitUntil(lambda: editor() is not None and editor().property("text") == "Unsaved draft")
    qtbot.wait(750)
    assert service.repository.segment(segment["id"])["target_text"] == "External new version"
    assert editor().property("text") == "Unsaved draft"
    controller.discardDraft(segment["id"])
    tabs.setProperty("currentIndex", 3)

    def click_item(control):
        qtbot.waitUntil(lambda: control.isVisible() and control.isEnabled())
        position = control.mapToScene(QPointF(control.width() / 2, control.height() / 2)).toPoint()
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, position)

    click_item(root.findChild(QObject, "deepReviewButton"))
    review = root.findChild(QObject, "reviewDialog")
    qtbot.waitUntil(lambda: review.property("visible"), timeout=10_000)
    assert root.property("reviewEstimate")["estimated_calls"] == 1
    review.close()
    qtbot.waitUntil(lambda: not review.property("visible"))
    tabs.setProperty("currentIndex", 5)

    def find_preview(parent):
        for child in parent.childItems():
            if (
                child.objectName() == "artifactPreviewButton"
                and child.property("artifactPath") == exported["artifact_path"]
            ):
                return child
            found = find_preview(child)
            if found is not None:
                return found
        return None

    qtbot.waitUntil(lambda: find_preview(root.contentItem()) is not None)
    preview_button = find_preview(root.contentItem())
    click_item(preview_button)
    qtbot.waitUntil(lambda: root.findChild(QObject, "previewDialog").property("visible"))
    qtbot.waitUntil(
        lambda: "Initial translation" in root.property("previewContent"), timeout=10_000
    )
    root.close()
    controller.deleteLater()
    engine.deleteLater()
