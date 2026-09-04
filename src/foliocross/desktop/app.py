"""Desktop application entry point."""

from __future__ import annotations

import os
import sys
from importlib.resources import files

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon

from ..infrastructure.workspace import Workspace
from .controller import DesktopController


def run_desktop(workspace: Workspace | None = None) -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_VARIANT", "Dense")
    QQuickStyle.setStyle("Material")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("FolioCross")
    app.setOrganizationName("FolioCross")
    engine = QQmlApplicationEngine()
    controller = DesktopController(workspace or Workspace.default())
    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView)
        tray = QSystemTrayIcon(icon, app)
        tray.setToolTip("FolioCross")
        tray.show()

        def notify(event_type: str, payload: str) -> None:
            del payload
            if event_type == "job.completed":
                tray.showMessage("FolioCross", "图书翻译与导出已经完成。")
            elif event_type == "job.failed":
                tray.showMessage(
                    "FolioCross",
                    "图书翻译失败，请回到任务工作台查看原因。",
                    QSystemTrayIcon.Critical,
                )

        controller.workerEvent.connect(notify)
    engine.rootContext().setContextProperty("backend", controller)
    qml = files("foliocross.desktop.qml").joinpath("Main.qml")
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        return 1
    engine.rootContext().setContextProperty("trayAvailable", tray is not None)
    return app.exec()
