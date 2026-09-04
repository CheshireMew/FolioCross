from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtQml import QQmlApplicationEngine

from foliocross.application.service import FolioCrossService
from foliocross.desktop.controller import DesktopController


def test_main_qml_loads_offscreen(qtbot, workspace):
    engine = QQmlApplicationEngine()
    controller = DesktopController(workspace)
    engine.rootContext().setContextProperty("backend", controller)
    qml = files("foliocross.desktop.qml").joinpath("Main.qml")
    engine.load(QUrl.fromLocalFile(str(qml)))
    assert len(engine.rootObjects()) == 1
    root = engine.rootObjects()[0]
    root.setProperty("pageIndex", 1)
    root.setProperty("detailTab", 4)
    assert root.property("pageIndex") == 1
    assert root.property("detailTab") == 4


def test_controller_persists_language_scale_selection_and_editor_state(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    source = tmp_path / "desktop.txt"
    source.write_text("Editable paragraph.", encoding="utf-8")
    job_id = service.import_book(str(source))["job_id"]
    controller = DesktopController(workspace)
    controller.setLanguage("en")
    controller.setUiScale(1.25)
    controller.setDarkMode(True)
    controller.selectJob(job_id)
    chapter_id = controller.selectedChapterId
    segment = controller.segments[0]
    saved_version = controller.saveSegment(segment["id"], "人工译文", segment["version"])
    assert saved_version == 1
    assert controller.segments[0]["version"] == 1
    assert controller.segments[0]["locked"] is True
    controller.saveDetailTab(job_id, 3)
    controller.saveEditorPosition(job_id, chapter_id, 126.5)

    restored = DesktopController(workspace)
    assert restored.uiLanguage == "en"
    assert restored.t("library") == "Library"
    assert restored.uiScale == 1.25
    assert restored.darkMode is True
    assert restored.selectedJob["id"] == job_id
    assert restored.selectedChapterId == chapter_id
    assert restored.detailTab(job_id) == 3
    assert restored.editorPosition(job_id, chapter_id) == 126.5
    assert restored.segments[0]["target_text"] == "人工译文"


def test_controller_queues_and_can_pause_waiting_job(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("First.", encoding="utf-8")
    second.write_text("Second.", encoding="utf-8")
    first_job = service.import_book(str(first))["job_id"]
    second_job = service.import_book(str(second))["job_id"]
    controller = DesktopController(workspace)
    controller._processes[first_job] = QProcess(controller)

    controller.startJob(second_job)
    assert service.repository.get_job(second_job)["status"] == "queued"
    assert service.repository.get_job(second_job)["desired_state"] == "run"
    controller.pauseJob(second_job)
    assert service.repository.get_job(second_job)["status"] == "paused"
    assert service.repository.get_job(second_job)["desired_state"] == "pause"


def test_controller_saves_advanced_limits_and_force_stop_kills_worker(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    source = tmp_path / "controlled.txt"
    source.write_text("Controlled paragraph.", encoding="utf-8")
    job_id = service.import_book(str(source))["job_id"]
    controller = DesktopController(workspace)
    configured = controller.configureJob(
        job_id, "en", "epub", False, "1.5", "2.0", 3, "60", "90000", "save"
    )
    assert configured is True
    config = service.repository.get_job(job_id)["config"]
    assert config["translation_max_concurrency"] == 3
    assert config["requests_per_minute"] == 60
    assert config["tokens_per_minute"] == 90000

    class DummyProcess:
        killed = False

        def kill(self):
            self.killed = True

    process = DummyProcess()
    controller._processes[job_id] = process
    controller.forceStopJob(job_id)
    assert process.killed is True
    job = service.repository.get_job(job_id)
    assert job["status"] == "interrupted"
    assert job["desired_state"] == "pause"
    assert (
        controller._process_error_message(
            '{"ok":false,"error":{"code":"x","message":"可读错误","details":{}}}'
        )
        == "可读错误"
    )
