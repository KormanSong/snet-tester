"""Launch Qt Designer with the main_window.ui file."""

import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path


def _find_designer() -> str | None:
    """Find designer.exe on PATH or inside known package locations."""
    # 1) PATH에서 designer / designer.exe 탐색
    found = shutil.which("designer")
    if found:
        return found

    # 2) PySide6 패키지 내 designer.exe 탐색 (PyQt5에는 미포함)
    try:
        import PySide6
        candidate = Path(PySide6.__file__).parent / "designer.exe"
        if candidate.exists():
            return str(candidate)
    except ImportError:
        pass

    # 3) uv 캐시 내 PySide6 designer.exe 탐색 (fallback)
    uv_cache = Path.home() / "AppData" / "Local" / "uv" / "cache"
    if uv_cache.exists():
        for hit in uv_cache.rglob("PySide6/designer.exe"):
            return str(hit)

    return None


def main() -> int:
    ui = str(files("snet_tester2").joinpath("resources/ui/main_window.ui"))
    designer = _find_designer()
    if designer is None:
        print("Error: designer.exe not found.", file=sys.stderr)
        print("Install PySide6 (`uv pip install PySide6`) or add designer.exe to PATH.", file=sys.stderr)
        return 1
    return subprocess.call([designer, ui])


if __name__ == "__main__":
    raise SystemExit(main())
