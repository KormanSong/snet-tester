"""Allow running with: python -m snet_tester"""

import os
import pathlib

# Auto-detect Qt platform plugin path for venv environments
_qt_plugins = pathlib.Path(__file__).resolve().parents[1] / ".venv" / "Lib" / "site-packages" / "PyQt5" / "Qt5" / "plugins" / "platforms"
if _qt_plugins.exists() and not os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(_qt_plugins)

from .main import main

raise SystemExit(main())
