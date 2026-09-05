from importlib.resources import files
from pathlib import Path

from conftest import write_sample_epub
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from shiboken6 import getCppPointer, wrapInstance

from foliocross.application.service import FolioCrossService
from foliocross.desktop.controller import DesktopController
from foliocross.infrastructure.formats.markers import strip_protected_markers, validate_markers


def _visual_child(item: QQuickItem, object_name: str):
    for child in item.childItems():
        if child.objectName() == object_name:
            return child
        nested = _visual_child(child, object_name)
        if nested is not None:
            return nested
    return None


def _visual_child_for_segment(item: QQuickItem, object_name: str, segment_id: str):
    for child in item.childItems():
        if child.objectName() == object_name and child.property("segmentId") == segment_id:
            return child
        nested = _visual_child_for_segment(child, object_name, segment_id)
        if nested is not None:
            return nested
    return None


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
    settings = root.findChild(QObject, "navSettingsButton")
    library_shortcut = root.findChild(QObject, "shortcutLibrary")
    refresh_shortcut = root.findChild(QObject, "shortcutRefresh")
    assert settings is not None
    assert library_shortcut is not None
    assert refresh_shortcut is not None
    root.setProperty("pageIndex", 0)
    settings.click()
    assert root.property("pageIndex") == 1
    library_shortcut.activated.emit()
    assert root.property("pageIndex") == 0
    assert "Ctrl+R" in [str(value) for value in refresh_shortcut.property("sequences")]


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
    restored.service.repository.update_job(job_id, status="queued", message="已进入中文队列")
    restored.refresh()
    assert restored.selectedJob["display_message"] == (
        "The job is queued and will start automatically."
    )
    assert restored.localizeText("完全未知的中文状态") == (
        "FolioCross updated the job. See its current status and log for details."
    )


def test_qml_start_button_enqueues_durable_background_job(qtbot, workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    source = tmp_path / "start-from-qml.txt"
    source.write_text("Start this job from the real QML button.", encoding="utf-8")
    job_id = service.import_book(str(source))["job_id"]
    started = []
    controller = DesktopController(workspace, scheduler_starter=lambda value: started.append(value))
    controller.selectJob(job_id)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", controller)
    qml = files("foliocross.desktop.qml").joinpath("Main.qml")
    engine.load(QUrl.fromLocalFile(str(qml)))
    root = engine.rootObjects()[0]
    qtbot.waitExposed(root)
    button = root.findChild(QObject, "startJobButton")
    assert button is not None
    assert button.property("enabled") is True

    button.click()

    operation = service.repository.active_background_operation(job_id)
    assert operation is not None
    assert operation["action"] == "run"
    assert service.repository.get_job(job_id)["status"] == "queued"
    assert started

    service.repository.mark_background_operation_running(operation["id"], 999999)
    service.repository.update_job(job_id, status="translating", stage="translate")
    controller.refresh()
    pause = root.findChild(QObject, "pauseJobButton")
    assert pause is not None
    assert pause.property("enabled") is True
    pause.click()
    assert service.repository.get_job(job_id)["desired_state"] == "pause"


def test_qml_translation_editor_debounces_and_locks_manual_edit(qtbot, workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    service.repository.set_setting("first_run_complete", True)
    source = write_sample_epub(tmp_path / "edit-from-qml.epub")
    job_id = service.import_book(str(source))["job_id"]
    chapters = service.repository.chapters_for_job(job_id)
    marker_segment = next(
        segment
        for chapter_row in chapters
        for segment in service.repository.segments_for_chapter(chapter_row["id"])
        if segment["markers"]
    )
    chapter = next(row for row in chapters if row["id"] == marker_segment["chapter_id"])
    service.edit_segment(marker_segment["id"], marker_segment["source_text"], expected_version=0)
    controller = DesktopController(workspace, scheduler_starter=lambda value: 0)
    controller.selectJob(job_id)
    controller.selectChapter(chapter["id"])
    segment_id = marker_segment["id"]
    segment_index = next(
        index for index, segment in enumerate(controller.segments) if segment["id"] == segment_id
    )
    assert "⟦FC:" not in controller.segments[segment_index]["source_display_text"]
    assert "⟦FC:" not in controller.segments[segment_index]["target_display_text"]
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", controller)
    qml = files("foliocross.desktop.qml").joinpath("Main.qml")
    engine.load(QUrl.fromLocalFile(str(qml)))
    root = engine.rootObjects()[0]
    qtbot.waitExposed(root)
    tabs = root.findChild(QObject, "detailTabs")
    assert tabs is not None
    tabs.setProperty("currentIndex", 1)
    qtbot.waitUntil(lambda: root.property("detailTab") == 1)
    detail_pages = root.findChild(QObject, "detailPages")
    assert detail_pages is not None
    qtbot.waitUntil(lambda: detail_pages.property("currentIndex") == 1)
    editor_page = root.findChild(QObject, "editorPage")
    editor_layout = root.findChild(QObject, "editorLayout")
    assert editor_page is not None
    assert editor_layout is not None
    segment_list = root.findChild(QObject, "segmentList")
    assert segment_list is not None
    assert segment_list.property("count") == len(controller.segments)
    assert segment_list.property("visible") is True
    assert editor_page.property("width") > 0
    assert editor_page.property("height") > 0
    assert editor_layout.property("width") > 0
    assert editor_layout.property("height") > 0
    assert segment_list.property("width") > 0, (
        root.property("width"),
        root.property("pageIndex"),
        tabs.property("width"),
        detail_pages.property("width"),
        detail_pages.property("height"),
        editor_page.property("width"),
        editor_page.property("height"),
        editor_layout.property("width"),
        editor_layout.property("height"),
        segment_list.property("height"),
    )
    assert segment_list.property("height") > 0
    segment_list.positionViewAtIndex(segment_index, 0)
    segment_list.forceLayout()
    segment_item = wrapInstance(getCppPointer(segment_list)[0], QQuickItem)
    qtbot.waitUntil(
        lambda: _visual_child_for_segment(segment_item, "translationEditor", segment_id) is not None
    )
    editor = _visual_child_for_segment(segment_item, "translationEditor", segment_id)
    source_label = _visual_child_for_segment(segment_item, "sourceTextLabel", segment_id)
    status_label = _visual_child_for_segment(segment_item, "segmentStatusLabel", segment_id)
    assert "⟦FC:" not in editor.property("text")
    assert "⟦FC:" not in source_label.property("text")
    assert status_label.property("text") == "人工锁定"

    editor.forceActiveFocus()
    qtbot.waitUntil(lambda: editor.property("activeFocus") is True)
    editor.setProperty("text", "通过真实界面保存的人工译文")
    qtbot.waitUntil(
        lambda: (
            strip_protected_markers(service.repository.segment(segment_id)["target_text"])
            == "通过真实界面保存的人工译文"
        ),
        timeout=2500,
    )

    saved = service.repository.segment(segment_id)
    assert saved["locked"] is True
    assert saved["version"] == 2
    assert validate_markers(saved["target_text"], saved["markers"]) == []
    assert service.repository.segment_revisions(segment_id)[0]["origin"] == "manual"


def test_controller_queues_and_can_pause_waiting_job(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("First.", encoding="utf-8")
    second.write_text("Second.", encoding="utf-8")
    first_job = service.import_book(str(first))["job_id"]
    second_job = service.import_book(str(second))["job_id"]
    started = []
    controller = DesktopController(workspace, scheduler_starter=lambda value: started.append(value))

    controller.startJob(first_job)
    controller.startJob(second_job)
    assert len(service.repository.background_operations("queued")) == 2
    assert service.repository.get_job(second_job)["status"] == "queued"
    assert service.repository.get_job(second_job)["desired_state"] == "run"
    controller.pauseJob(second_job)
    assert service.repository.get_job(second_job)["status"] == "paused"
    assert service.repository.get_job(second_job)["desired_state"] == "pause"
    assert service.repository.active_background_operation(second_job) is None
    assert started


def test_controller_pages_and_searches_large_glossary(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    source = tmp_path / "large-glossary.txt"
    source.write_text("A source paragraph.", encoding="utf-8")
    job_id = service.import_book(str(source))["job_id"]
    service.repository.upsert_glossary_terms(
        job_id,
        [{"source": f"Term {index:03d}", "target": f"术语 {index:03d}"} for index in range(250)],
    )
    controller = DesktopController(workspace, scheduler_starter=lambda value: 0)
    controller.selectJob(job_id)
    assert controller.glossaryTotal == 250
    assert len(controller.glossary) == 100
    controller.loadMoreGlossary()
    assert len(controller.glossary) == 200
    controller.loadMoreGlossary()
    assert len(controller.glossary) == 250
    controller.searchGlossary("Term 249")
    assert controller.glossaryTotal == 1
    assert controller.glossary[0]["target"] == "术语 249"


def test_controller_saves_advanced_limits_and_requests_force_stop(workspace, tmp_path: Path):
    service = FolioCrossService(workspace)
    source = tmp_path / "controlled.txt"
    source.write_text("Controlled paragraph.", encoding="utf-8")
    job_id = service.import_book(str(source))["job_id"]
    started = []
    controller = DesktopController(workspace, scheduler_starter=lambda value: started.append(value))
    configured = controller.configureJob(
        job_id, "en", "epub", False, "1.5", "2.0", 3, "60", "90000", "save"
    )
    assert configured is True
    config = service.repository.get_job(job_id)["config"]
    assert config["translation_max_concurrency"] == 3
    assert config["requests_per_minute"] == 60
    assert config["tokens_per_minute"] == 90000

    operation = service.repository.enqueue_background_operation(job_id, "run")
    service.repository.mark_background_operation_running(operation["id"], 999999)
    controller.forceStopJob(job_id)
    active = service.repository.active_background_operation(job_id)
    assert active is not None
    assert active["cancel_requested"] is True
    assert service.repository.get_job(job_id)["desired_state"] == "pause"
    assert started
    assert (
        controller._process_error_message(
            '{"ok":false,"error":{"code":"x","message":"可读错误","details":{}}}'
        )
        == "可读错误"
    )
