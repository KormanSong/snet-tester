"""UI consistency checker — detects unannotated static UI property settings.

Scans snet_tester2/views/*.py for patterns that set static UI properties
(setFont, setSizePolicy, setStyleSheet, etc.) without a preceding
# ui-override: or # ui-dynamic: annotation comment.

Usage:
    python tools/check_ui_consistency.py          # scan and report
    python tools/check_ui_consistency.py --strict  # exit 1 on any violation

This is a Tier-2 check (annotation presence only). It does NOT determine
whether the annotation reason is valid — that is a human review concern.

Classification policy (Tier 1, defined in CLAUDE.md):
  - Static property    → must be in .ui, Python forbidden
  - State-based dynamic → # ui-override: allowed
  - Data-dependent     → # ui-dynamic: allowed
  - Designer-unsupported → # ui-override: + directive registration
  - Widget replacement → # ui-dynamic: + directive registration
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns that indicate static UI property setting
SUSPECT_PATTERNS = [
    (re.compile(r'\.\s*setMinimumSize\s*\('), 'setMinimumSize'),
    (re.compile(r'\.\s*setMaximumSize\s*\('), 'setMaximumSize'),
    (re.compile(r'\.\s*setFixedSize\s*\('), 'setFixedSize'),
    (re.compile(r'\.\s*setSizePolicy\s*\('), 'setSizePolicy'),
    (re.compile(r'\.\s*setFont\s*\('), 'setFont'),
    (re.compile(r'\.\s*setStyleSheet\s*\('), 'setStyleSheet'),
    (re.compile(r'\.\s*setContentsMargins\s*\('), 'setContentsMargins'),
    (re.compile(r'\.\s*setSpacing\s*\('), 'setSpacing'),
    (re.compile(r'\.\s*setMinimumWidth\s*\('), 'setMinimumWidth'),
    (re.compile(r'\.\s*setMinimumHeight\s*\('), 'setMinimumHeight'),
    (re.compile(r'\.\s*setMaximumWidth\s*\('), 'setMaximumWidth'),
    (re.compile(r'\.\s*setMaximumHeight\s*\('), 'setMaximumHeight'),
]

# Exempt comment pattern: # ui-override: ... or # ui-dynamic: ...
EXEMPT_RE = re.compile(r'#\s*ui-(override|dynamic):')


def check_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Check a single file for unannotated suspect patterns.

    Returns list of (line_number, pattern_name, line_text) violations.
    """
    violations = []
    lines = filepath.read_text(encoding='utf-8', errors='ignore').splitlines()

    for i, line in enumerate(lines):
        # Skip comment-only lines
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue

        for pattern, name in SUSPECT_PATTERNS:
            if pattern.search(line):
                # Check current line for inline exempt comment
                if EXEMPT_RE.search(line):
                    break
                # Check previous line for exempt comment
                if i > 0 and EXEMPT_RE.search(lines[i - 1]):
                    break
                # Check two lines above (comment might be separated by blank)
                if i > 1 and EXEMPT_RE.search(lines[i - 2]) and lines[i - 1].strip() == '':
                    break
                violations.append((i + 1, name, line.rstrip()))
                break  # one violation per line

    return violations


def main():
    strict = '--strict' in sys.argv

    views_dir = Path(__file__).parent.parent / 'snet_tester2' / 'views'
    if not views_dir.exists():
        print(f'Views directory not found: {views_dir}')
        sys.exit(1)

    total_violations = 0
    for py_file in sorted(views_dir.glob('*.py')):
        violations = check_file(py_file)
        if violations:
            print(f'\n{py_file.name}:')
            for lineno, name, text in violations:
                print(f'  L{lineno}: [{name}] {text.strip()}')
            total_violations += len(violations)

    print(f'\n{"=" * 50}')
    if total_violations == 0:
        print('  UI consistency check: PASS (0 violations)')
    else:
        print(f'  UI consistency check: {total_violations} violation(s) found')
        print('  Add # ui-override: or # ui-dynamic: annotation to each.')

    if strict and total_violations > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
