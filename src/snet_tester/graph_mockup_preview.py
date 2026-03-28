"""Entry point for the graph aspect ratio mockup preview."""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

from PyQt5 import QtWidgets

if __package__ in {None, ""}:
    project_root = pathlib.Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from snet_tester import configure_qt_environment
    from snet_tester.views.graph_mockup_window import GraphMockupWindow
else:
    from . import configure_qt_environment
    from .views.graph_mockup_window import GraphMockupWindow


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview the graph aspect ratio mockup.")
    parser.add_argument(
        "--export",
        type=pathlib.Path,
        help="Render the preview to an image file and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.export and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    configure_qt_environment()
    app = QtWidgets.QApplication(sys.argv if argv is None else argv)
    window = GraphMockupWindow()

    if args.export:
        export_path = args.export.resolve()
        export_path.parent.mkdir(parents=True, exist_ok=True)
        window.show()
        app.processEvents()
        window.grab().save(str(export_path))
        return 0

    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
