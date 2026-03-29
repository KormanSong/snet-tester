"""SNET Protocol Tester v2 entry point — PySide6."""

import argparse
import sys

from PySide6 import QtGui, QtWidgets

from . import configure_qt_environment
from .views.main_window import MainWindow


def _build_light_palette() -> QtGui.QPalette:
    """Build an explicit light palette — immune to OS dark mode."""
    pal = QtGui.QPalette()
    white = QtGui.QColor(255, 255, 255)
    light_gray = QtGui.QColor(240, 240, 240)
    mid_gray = QtGui.QColor(160, 160, 160)
    dark = QtGui.QColor(0, 0, 0)
    highlight = QtGui.QColor(48, 140, 198)

    pal.setColor(QtGui.QPalette.Window, light_gray)
    pal.setColor(QtGui.QPalette.WindowText, dark)
    pal.setColor(QtGui.QPalette.Base, white)
    pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(245, 245, 245))
    pal.setColor(QtGui.QPalette.Text, dark)
    pal.setColor(QtGui.QPalette.Button, light_gray)
    pal.setColor(QtGui.QPalette.ButtonText, dark)
    pal.setColor(QtGui.QPalette.BrightText, QtGui.QColor(255, 0, 0))
    pal.setColor(QtGui.QPalette.Highlight, highlight)
    pal.setColor(QtGui.QPalette.HighlightedText, white)
    pal.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(255, 255, 220))
    pal.setColor(QtGui.QPalette.ToolTipText, dark)
    pal.setColor(QtGui.QPalette.PlaceholderText, mid_gray)
    pal.setColor(QtGui.QPalette.Light, white)
    pal.setColor(QtGui.QPalette.Midlight, QtGui.QColor(227, 227, 227))
    pal.setColor(QtGui.QPalette.Mid, mid_gray)
    pal.setColor(QtGui.QPalette.Dark, QtGui.QColor(100, 100, 100))
    pal.setColor(QtGui.QPalette.Shadow, QtGui.QColor(60, 60, 60))
    pal.setColor(QtGui.QPalette.Link, QtGui.QColor(0, 0, 255))
    pal.setColor(QtGui.QPalette.LinkVisited, QtGui.QColor(128, 0, 128))

    # Disabled state
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, mid_gray)
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, mid_gray)
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, mid_gray)

    return pal


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='SNET Protocol Tester v2')
    parser.add_argument('--mock', action='store_true', help='Run with mock serial data.')
    parser.add_argument('--port', type=str, default='COM6', help='Serial port (default: COM6)')
    parser.add_argument('--baud', type=int, default=115200, help='Baud rate (default: 115200)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    configure_qt_environment()

    app = QtWidgets.QApplication(sys.argv if argv is None else argv)

    # Force Fusion style + explicit light palette to prevent OS dark mode
    # from altering UI colors. Industrial equipment must look identical everywhere.
    app.setStyle('Fusion')
    app.setPalette(_build_light_palette())

    window = MainWindow(mock_mode=args.mock, port=args.port, baud=args.baud)
    window.show()
    exit_code = app.exec()
    window.shutdown()
    window.print_summary()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
