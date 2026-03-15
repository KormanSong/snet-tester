import argparse
import sys

from PyQt5 import QtWidgets

from main_window import MainWindow


# Bootstrap entry point for the Qt application.
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='USART I/O Mode Tool')
    parser.add_argument(
        '--mock',
        action='store_true',
        help='Run the UI without serial hardware and feed mock TX/RX samples.',
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    app = QtWidgets.QApplication(sys.argv if argv is None else argv)
    window = MainWindow(mock_mode=args.mock)
    window.show()
    exit_code = app.exec_()
    window.shutdown()
    window.print_summary()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
