"""Shared UI helper functions."""

import pathlib

from PyQt5 import QtCore, QtGui, QtWidgets, uic

from ..protocol.constants import PLACEHOLDER

UI_DIR = pathlib.Path(__file__).resolve().parent.parent / 'ui'


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


def load_ui(widget, filename: str):
    path = ui_path(filename)
    if not path.exists():
        raise FileNotFoundError(f'UI file not found: {path}')
    uic.loadUi(str(path), widget)


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
    text_edit.setReadOnly(True)
    text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
    text_edit.setFont(font)
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
    label.setFont(font)
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


def build_line_edit_style(background: str, border: str = '#B0B0B0') -> str:
    return (
        'QLineEdit {'
        f' background-color: {background};'
        f' border: 1px solid {border};'
        ' border-radius: 4px;'
        ' padding: 2px 6px;'
        '}'
    )
