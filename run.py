"""Entry point for PyInstaller exe build."""

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from snet_tester.main import main

raise SystemExit(main())
