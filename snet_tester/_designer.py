"""Launch Qt Designer with the main_window.ui file."""

import shutil
import subprocess
import sys
from importlib.resources import files


def main() -> int:
    ui = str(files("snet_tester").joinpath("resources/ui/main_window.ui"))
    designer = shutil.which("designer")
    if designer is None:
        print("Error: designer.exe not found on PATH", file=sys.stderr)
        return 1
    return subprocess.call([designer, ui])


if __name__ == "__main__":
    raise SystemExit(main())
