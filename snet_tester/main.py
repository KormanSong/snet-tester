"""SNET Protocol Tester entry point."""

import argparse
import pathlib
import sys

from PyQt5 import QtWidgets

if __package__ in {None, ""}:
    project_root = pathlib.Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from snet_tester import configure_qt_environment
    from snet_tester.config import SerialConfig
    from snet_tester.views.main_window import MainWindow
else:
    from . import configure_qt_environment
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

    configure_qt_environment()

    app = QtWidgets.QApplication(sys.argv if argv is None else argv)
    window = MainWindow(mock_mode=args.mock, config=config)
    window.show()
    exit_code = app.exec_()
    window.shutdown()
    window.print_summary()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
