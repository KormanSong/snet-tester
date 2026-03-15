"""SNET Protocol Tester entry point."""

import argparse
import sys

from PyQt5 import QtWidgets

from .config import SerialConfig
from .views.main_window import MainWindow


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='SNET Protocol Tester')
    parser.add_argument('--mock', action='store_true', help='Run with mock serial data.')
    parser.add_argument('--port', type=str, default='COM6', help='Serial port (default: COM6)')
    parser.add_argument('--baud', type=int, default=115200, help='Baud rate (default: 115200)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = SerialConfig(port=args.port, baud=args.baud)

    app = QtWidgets.QApplication(sys.argv if argv is None else argv)
    window = MainWindow(mock_mode=args.mock, config=config)
    window.show()
    exit_code = app.exec_()
    window.shutdown()
    window.print_summary()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
