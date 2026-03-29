"""UI consistency checker — detects unannotated static UI property settings.

Scans snet_tester2/views/*.py for calls that set visual UI properties
without a preceding # ui-override: or # ui-dynamic: annotation.

Design:
  1. Scan upward from each suspect line for the nearest annotation within
     the same indentation block (up to 15 lines).
  2. Exclude known non-UI contexts: QPainter methods, lambda internals,
     state-based conditionals (if/else branches with setStyleSheet).
  3. Report only genuine unannotated static property settings.

Usage:
    python tools/check_ui_consistency.py          # scan and report
    python tools/check_ui_consistency.py --strict  # exit 1 on any violation
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Suspect patterns: method calls that set static UI properties
# ---------------------------------------------------------------------------

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

# Exempt annotation pattern
EXEMPT_RE = re.compile(r'#\s*ui-(override|dynamic):')

# ---------------------------------------------------------------------------
# False-positive exclusion rules
# ---------------------------------------------------------------------------

# Lines matching these are NOT UI property settings (rendering, lambdas, etc.)
EXCLUDE_PATTERNS = [
    re.compile(r'painter\.\s*setFont'),          # QPainter rendering
    re.compile(r'lambda\s.*\.set(Font|StyleSheet)'),  # lambda internals
]

# Lines inside if/elif/else blocks that toggle state are dynamic (not static)
STATE_TOGGLE_CONTEXT_RE = re.compile(
    r'^\s*(if|elif|else)\b.*\b(dirty|clean|synced|running|checked|active|error|applied)\b',
    re.IGNORECASE,
)


def _is_excluded(line: str) -> bool:
    """Return True if the line matches a known false-positive pattern."""
    for pat in EXCLUDE_PATTERNS:
        if pat.search(line):
            return True
    return False


def _has_annotation_above(lines: list[str], target_idx: int, max_scan: int = 15) -> bool:
    """Scan upward from target_idx for a # ui-override: or # ui-dynamic: comment.

    Stops scanning when:
    - An annotation is found (return True)
    - A line with less indentation than the target is hit (block boundary)
    - max_scan lines have been checked
    - Beginning of file is reached
    """
    target_indent = len(lines[target_idx]) - len(lines[target_idx].lstrip())

    for offset in range(1, max_scan + 1):
        check_idx = target_idx - offset
        if check_idx < 0:
            break
        check_line = lines[check_idx]
        stripped = check_line.strip()

        # Found annotation
        if EXEMPT_RE.search(check_line):
            return True

        # Skip blank lines and comments (keep scanning)
        if stripped == '' or stripped.startswith('#'):
            continue

        # If this code line has LESS indentation, we've left the block
        line_indent = len(check_line) - len(check_line.lstrip())
        if line_indent < target_indent and stripped:
            # But check if THIS line is annotated (block header with comment)
            if EXEMPT_RE.search(check_line):
                return True
            break

    return False


def _is_in_state_toggle_block(lines: list[str], target_idx: int) -> bool:
    """Check if the target line is inside an if/elif/else block that toggles UI state."""
    target_indent = len(lines[target_idx]) - len(lines[target_idx].lstrip())

    for offset in range(1, 10):
        check_idx = target_idx - offset
        if check_idx < 0:
            break
        check_line = lines[check_idx]
        stripped = check_line.strip()
        if stripped == '':
            continue
        line_indent = len(check_line) - len(check_line.lstrip())
        if line_indent < target_indent:
            if STATE_TOGGLE_CONTEXT_RE.search(check_line):
                return True
            break
    return False


def check_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Check a single file for unannotated suspect patterns.

    Returns list of (line_number, pattern_name, line_text) violations.
    """
    violations = []
    lines = filepath.read_text(encoding='utf-8', errors='ignore').splitlines()

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue

        for pattern, name in SUSPECT_PATTERNS:
            if not pattern.search(line):
                continue

            # Exclusion 1: known non-UI patterns
            if _is_excluded(line):
                break

            # Exclusion 2: inline annotation
            if EXEMPT_RE.search(line):
                break

            # Exclusion 3: annotation within the block above
            if _has_annotation_above(lines, i):
                break

            # Exclusion 4: state-toggle context (if dirty/clean/synced/...)
            if _is_in_state_toggle_block(lines, i):
                break

            violations.append((i + 1, name, line.rstrip()))
            break

    return violations


def run_check() -> int:
    """Run the check and return the number of violations."""
    views_dir = Path(__file__).parent.parent / 'snet_tester2' / 'views'
    if not views_dir.exists():
        print(f'Views directory not found: {views_dir}')
        return -1

    total = 0
    for py_file in sorted(views_dir.glob('*.py')):
        violations = check_file(py_file)
        if violations:
            print(f'\n{py_file.name}:')
            for lineno, name, text in violations:
                print(f'  L{lineno}: [{name}] {text.strip()}')
            total += len(violations)

    print(f'\n{"=" * 50}')
    if total == 0:
        print('  UI consistency check: PASS (0 violations)')
    else:
        print(f'  UI consistency check: {total} violation(s) found')
        print('  Add # ui-override: or # ui-dynamic: annotation to each.')
    return total


def main():
    total = run_check()
    if '--strict' in sys.argv and total > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
