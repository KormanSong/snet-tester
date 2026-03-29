"""Automated UI consistency gate — runs as part of pytest.

Ensures all static UI property settings in snet_tester2/views/ have
a # ui-override: or # ui-dynamic: annotation.
"""

import sys
from pathlib import Path

def test_ui_consistency_zero_violations():
    """check_ui_consistency.py must report 0 violations."""
    tools_dir = Path(__file__).parent.parent / 'tools'
    sys.path.insert(0, str(tools_dir))
    from check_ui_consistency import run_check
    violations = run_check()
    assert violations == 0, f'UI consistency check found {violations} violation(s)'
