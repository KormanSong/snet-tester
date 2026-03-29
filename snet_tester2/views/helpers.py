"""Shared UI helper functions.

PySide6 port: replaces PyQt5 uic.loadUi with custom QUiLoader wrapper
that sets widget attributes on the base instance (spike-verified pattern).
"""

import pathlib
import sys

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QMetaObject

from ..protocol.constants import PLACEHOLDER


def _package_dir() -> pathlib.Path:
    """Return the snet_tester2 package directory, works both normally and in PyInstaller bundles."""
    if getattr(sys, 'frozen', False):
        return pathlib.Path(sys._MEIPASS) / 'snet_tester2'
    return pathlib.Path(__file__).resolve().parent.parent


RESOURCE_DIR = _package_dir() / 'resources'
UI_DIR = RESOURCE_DIR / 'ui'


def resource_path(*parts: str) -> pathlib.Path:
    return RESOURCE_DIR.joinpath(*parts)


def ui_path(filename: str) -> pathlib.Path:
    return UI_DIR / filename


def require_child(parent, child_type, name: str):
    child = parent.findChild(child_type, name)
    if child is None:
        parent_name = parent.objectName() or type(parent).__name__
        raise RuntimeError(f"Missing required widget '{name}' in '{parent_name}'")
    return child


def find_optional_child(parent, child_type, name: str):
    return parent.findChild(child_type, name)


class _UiLoader(QUiLoader):
    """Custom QUiLoader that populates widget attributes on a base instance.

    PySide6 QUiLoader does not have a direct equivalent of PyQt5's
    uic.loadUi(path, widget).  This wrapper intercepts createWidget calls
    so that:
    - The top-level widget returns the base instance instead of creating a new one.
    - QMainWindow special children (menubar, statusbar) are obtained from the
      base instance to avoid duplicates.
    - All named child widgets are set as attributes on the base instance.
    """

    def __init__(self, base_instance):
        super().__init__(base_instance)
        self._base = base_instance

    def createWidget(self, class_name, parent=None, name=""):
        # Top-level widget: return the base instance itself
        if parent is None and self._base is not None:
            return self._base

        # QMainWindow special children -- reuse existing bars
        if isinstance(self._base, QtWidgets.QMainWindow):
            if class_name == "QMenuBar":
                w = self._base.menuBar()
                if name:
                    setattr(self._base, name, w)
                return w
            if class_name == "QStatusBar":
                w = self._base.statusBar()
                if name:
                    setattr(self._base, name, w)
                return w

        widget = super().createWidget(class_name, parent, name)
        if self._base is not None and name:
            setattr(self._base, name, widget)
        return widget


def load_ui(widget, filename: str):
    """Load a .ui file into an existing widget instance (PySide6 equivalent of uic.loadUi).

    Args:
        widget: The target widget to populate (typically a QMainWindow or QWidget subclass).
        filename: Name of the .ui file relative to the UI_DIR.
    """
    path = ui_path(filename)
    if not path.exists():
        raise FileNotFoundError(f'UI file not found: {path}')
    loader = _UiLoader(widget)
    ui_file = QFile(str(path))
    if not ui_file.open(QFile.ReadOnly):
        raise FileNotFoundError(f'Cannot open: {path}')
    try:
        loader.load(ui_file, widget.parentWidget())
    finally:
        ui_file.close()
    QMetaObject.connectSlotsByName(widget)


def attach_widget(host: QtWidgets.QWidget, child: QtWidgets.QWidget):
    layout = host.layout()
    if layout is None:
        layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
    clear_layout(layout)
    layout.addWidget(child)


def clear_layout(layout: QtWidgets.QLayout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().setParent(None)
        elif item.layout() is not None:
            clear_layout(item.layout())


def configure_plain_text_edit(text_edit: QtWidgets.QPlainTextEdit, font: QtGui.QFont):
    # readOnly and lineWrapMode are set in .ui
    text_edit.setPlainText(PLACEHOLDER)


def build_fixed_font() -> QtGui.QFont:
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
    font.setPointSize(10)
    return font


def configure_value_label(
    label: QtWidgets.QLabel,
    font: QtGui.QFont,
    align: QtCore.Qt.AlignmentFlag = QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
):
    label.setAlignment(align)
    label.setText(PLACEHOLDER)


def set_badge(label: QtWidgets.QLabel, text: str, tone: str):
    styles = {
        'neutral': '#616161',
        'run': '#2E7D32',
        'stop': '#757575',
        'ok': '#1565C0',
        'warn': '#EF6C00',
        'error': '#C62828',
    }
    color = styles.get(tone, styles['neutral'])
    label.setText(text)
    label.setStyleSheet(
        'QLabel {'
        f' background-color: {color};'
        ' color: white;'
        ' border-radius: 4px;'
        ' padding: 3px 8px;'
        ' font-weight: 600;'
        '}'
    )


def ensure_table_shape(table: QtWidgets.QTableWidget, rows: int, cols: int, table_name: str):
    if table.rowCount() != rows or table.columnCount() != cols:
        raise RuntimeError(
            f"Table '{table_name}' shape mismatch: expected {rows}x{cols}, "
            f"got {table.rowCount()}x{table.columnCount()}"
        )
