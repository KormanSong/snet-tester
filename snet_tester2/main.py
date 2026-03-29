"""SNET Protocol Tester v2 entry point — PySide6."""

import argparse
import sys

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from . import configure_qt_environment
from .views.main_window import MainWindow


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

    # Force light color scheme while keeping the native Windows 11 style.
    # This prevents dark mode from corrupting .ui-designed colors without
    # altering widget metrics, shadows, or native appearance.
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    window = MainWindow(mock_mode=args.mock, port=args.port, baud=args.baud)
    window.show()
    exit_code = app.exec()
    window.shutdown()
    window.print_summary()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
