"""PySide6 QUiLoader baseinstance wrapper — spike validation.

Implements the same semantics as PyQt5's uic.loadUi(path, baseinstance):
  - Root widget request (parent=None) returns the existing instance
  - Child widgets are set as attributes on baseinstance via setattr
  - QMainWindow menuBar/statusBar de-duplication

Reference: qtpy (Spyder IDE) project's UiLoader implementation.
"""

from __future__ import annotations

from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QMainWindow, QWidget
from PySide6.QtCore import QFile, QMetaObject


class _UiLoader(QUiLoader):
    """QUiLoader subclass that populates an existing widget instance."""

    def __init__(self, base_instance: QWidget):
        super().__init__(base_instance)
        self._base = base_instance

    def createWidget(
        self, class_name: str, parent: QWidget | None = None, name: str = ""
    ) -> QWidget:
        # 1. Root widget → return existing instance
        if parent is None and self._base is not None:
            return self._base

        # 2. QMainWindow special children — prevent double creation
        if isinstance(self._base, QMainWindow):
            if class_name == "QMenuBar":
                widget = self._base.menuBar()
                if name:
                    setattr(self._base, name, widget)
                return widget
            if class_name == "QStatusBar":
                widget = self._base.statusBar()
                if name:
                    setattr(self._base, name, widget)
                return widget

        # 3. Normal widget — create and bind as attribute
        widget = super().createWidget(class_name, parent, name)
        if self._base is not None and name:
            setattr(self._base, name, widget)
        return widget


def load_ui(widget: QWidget, ui_path: str) -> None:
    """Drop-in replacement for PyQt5's uic.loadUi(path, widget)."""
    loader = _UiLoader(widget)
    ui_file = QFile(ui_path)
    if not ui_file.open(QFile.ReadOnly):
        raise FileNotFoundError(f"Cannot open UI file: {ui_path}")
    try:
        loader.load(ui_file, widget.parentWidget())
    finally:
        ui_file.close()
    QMetaObject.connectSlotsByName(widget)
