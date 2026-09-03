from importlib.resources import files

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine

from foliocross.desktop.controller import DesktopController


def test_main_qml_loads_offscreen(qtbot, workspace):
    engine = QQmlApplicationEngine()
    controller = DesktopController(workspace)
    engine.rootContext().setContextProperty("backend", controller)
    qml = files("foliocross.desktop.qml").joinpath("Main.qml")
    engine.load(QUrl.fromLocalFile(str(qml)))
    assert len(engine.rootObjects()) == 1
