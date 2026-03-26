"""Allow running with: python -m snet_tester."""

from . import configure_qt_environment
from .main import main

configure_qt_environment()

raise SystemExit(main())
