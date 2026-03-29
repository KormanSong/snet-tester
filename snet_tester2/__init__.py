"""SNET tester v2 package — PySide6 based."""

import os
import pathlib
import sys


def _qt_plugin_dir() -> pathlib.Path | None:
    try:
        import PySide6
    except ImportError:
        return None
    qt_plugins = pathlib.Path(PySide6.__file__).resolve().parent / "plugins" / "platforms"
    if qt_plugins.exists():
        return qt_plugins
    return None


def configure_qt_environment() -> None:
    """Set Qt plugin paths for source and editable-install runs on Windows."""
    if getattr(sys, "frozen", False) or os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
        return
    qt_plugins = _qt_plugin_dir()
    if qt_plugins is not None:
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_plugins)
