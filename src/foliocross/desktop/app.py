"""Desktop application entry point."""

from __future__ import annotations

import os
import sys
from importlib.resources import files

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ..infrastructure.workspace import Workspace
from .controller import DesktopController


def run_desktop(workspace: Workspace | None = None) -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_VARIANT", "Dense")
    QQuickStyle.setStyle("Material")
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.setApplicationName("FolioCross")
    app.setOrganizationName("FolioCross")
    engine = QQmlApplicationEngine()
    controller = DesktopController(workspace or Workspace.default())
    engine.rootContext().setContextProperty("backend", controller)
    qml = files("foliocross.desktop.qml").joinpath("Main.qml")
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        return 1
    return app.exec()
