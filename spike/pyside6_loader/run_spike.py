"""PySide6 UI Loader spike — gate validation G1~G5.

Gates:
  G1  setattr attribute access after load_ui
  G2  findChild == setattr identity
  G3  Nested widget access (plotPanel→plotHost, tx/rx/debug children)
  G4  QButtonGroup + idClicked signal (PySide6 replacement for buttonClicked[int])
  G5  pyqtgraph PlotWidget creation + require_child flow

Run:  python spike_test.py
Exit: 0 = all gates pass, 1 = at least one failure
"""

from __future__ import annotations

import os
import sys

# --- PySide6 must be imported before pyqtgraph for binding auto-detect ---
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QWidget,
)

UI_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "snet_tester", "resources", "ui", "main_window.ui",
    )
)

from spike_loader import load_ui


class TestMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        load_ui(self, UI_PATH)


# ---------------------------------------------------------------------------
# Gate functions
# ---------------------------------------------------------------------------


def gate_g1(w: TestMainWindow) -> bool:
    """G1: MAIN_WINDOW_OBJECTS accessible as self attributes after load_ui."""
    required = {
        "txPanel": (QWidget, QGroupBox),
        "rxPanel": (QWidget, QGroupBox),
        "plotPanel": (QGroupBox,),
        "debugTabWidget": (QTabWidget,),
    }
    for name, types in required.items():
        attr = getattr(w, name, None)
        if attr is None:
            print(f"  G1 FAIL: '{name}' not found as attribute")
            return False
        if not isinstance(attr, types):
            print(f"  G1 FAIL: '{name}' is {type(attr).__name__}, expected one of {[t.__name__ for t in types]}")
            return False
    return True


def gate_g2(w: TestMainWindow) -> bool:
    """G2: findChild result is the same object as the setattr'd attribute."""
    for name in ["txPanel", "rxPanel", "plotPanel", "debugTabWidget"]:
        by_attr = getattr(w, name, None)
        by_find = w.findChild(QWidget, name)
        if by_attr is None or by_find is None:
            print(f"  G2 FAIL: '{name}' — attr={by_attr}, find={by_find}")
            return False
        if by_attr is not by_find:
            print(f"  G2 FAIL: '{name}' — attr and findChild are different objects")
            return False
    return True


def gate_g3(w: TestMainWindow) -> bool:
    """G3: Nested widgets accessible via findChild on parent containers."""
    # --- plotPanel children ---
    plot_panel = getattr(w, "plotPanel", None)
    if plot_panel is None:
        print("  G3 FAIL: plotPanel not found")
        return False

    plot_host = plot_panel.findChild(QFrame, "plotHost")
    if plot_host is None:
        print("  G3 FAIL: plotHost not found inside plotPanel")
        return False

    for ch in range(1, 7):
        for prefix in ("legendTx", "legendRx"):
            name = f"{prefix}{ch}Button"
            if plot_panel.findChild(QPushButton, name) is None:
                print(f"  G3 FAIL: {name} not found inside plotPanel")
                return False

    # --- txPanel children (require_child targets) ---
    tx_panel = getattr(w, "txPanel", None)
    if tx_panel is None:
        print("  G3 FAIL: txPanel not found")
        return False
    for name, typ in [
        ("channelCountCombo", QComboBox),
        ("runButton", QPushButton),
        ("stopButton", QPushButton),
        ("setButton", QPushButton),
        ("ratioInput1", QLineEdit),
        ("ratioInput6", QLineEdit),
    ]:
        if tx_panel.findChild(typ, name) is None:
            print(f"  G3 FAIL: {name} not found inside txPanel")
            return False

    # --- rxPanel children ---
    rx_panel = getattr(w, "rxPanel", None)
    if rx_panel is None:
        print("  G3 FAIL: rxPanel not found")
        return False
    if rx_panel.findChild(QTableWidget, "rxMonitorTable") is None:
        print("  G3 FAIL: rxMonitorTable not found inside rxPanel")
        return False

    # --- debugTabWidget children ---
    debug = getattr(w, "debugTabWidget", None)
    if debug is None:
        print("  G3 FAIL: debugTabWidget not found")
        return False
    for name in ("txFrameTable", "txDataDump", "rxFrameTable", "rxDataDump"):
        if debug.findChild(QWidget, name) is None:
            print(f"  G3 FAIL: {name} not found inside debugTabWidget")
            return False

    # --- Optional widgets (find_optional_child targets) ---
    optional_found = 0
    for name in ("pressValueLabel", "tempValueLabel", "adCommandCheckBox",
                 "fullOpenControlCheckBox", "fullOpenValueEdit"):
        if rx_panel.findChild(QWidget, name) is not None:
            optional_found += 1
    print(f"  G3 INFO: {optional_found}/5 optional rxPanel widgets found")

    return True


def gate_g4(w: TestMainWindow) -> bool:
    """G4: QButtonGroup dynamic creation + idClicked signal (PySide6 Qt6 API)."""
    btn_all = w.findChild(QPushButton, "relayAllButton")
    if btn_all is None:
        print("  G4 SKIP: relayAllButton not in .ui (optional widget)")
        return True

    group = QButtonGroup(w)
    group.setExclusive(True)

    buttons: dict[int, QPushButton] = {}
    for ch in range(7):
        name = "relayAllButton" if ch == 0 else f"relayCh{ch}Button"
        btn = w.findChild(QPushButton, name)
        if btn is not None:
            group.addButton(btn, ch)
            buttons[ch] = btn

    if not buttons:
        print("  G4 FAIL: no relay buttons found")
        return False

    # Test idClicked signal (replaces PyQt5's buttonClicked[int])
    received: list[int] = []
    group.idClicked.connect(lambda id_: received.append(id_))

    # Simulate click on channel 1
    if 1 in buttons:
        buttons[1].click()
        if not received or received[-1] != 1:
            print(f"  G4 FAIL: idClicked not received correctly (got {received})")
            return False

    # Simulate click on ALL (channel 0)
    if 0 in buttons:
        buttons[0].click()
        if not received or received[-1] != 0:
            print(f"  G4 FAIL: idClicked for ALL not received (got {received})")
            return False

    print(f"  G4 INFO: idClicked signals received: {received}")
    return True


def gate_g5(w: TestMainWindow) -> bool:
    """G5: pyqtgraph PlotWidget creation inside loaded UI + require_child pattern."""
    try:
        import pyqtgraph as pg
    except ImportError:
        print("  G5 FAIL: pyqtgraph not installed in spike venv")
        return False

    # Verify pyqtgraph detected PySide6
    qt_lib = getattr(pg.Qt, "QT_LIB", None) or getattr(pg.Qt, "QtLib", "unknown")
    print(f"  G5 INFO: pyqtgraph Qt binding = {qt_lib}")

    # Find the plot host frame (where PlotWidgets would be embedded)
    plot_panel = getattr(w, "plotPanel", None)
    if plot_panel is None:
        print("  G5 FAIL: plotPanel not found")
        return False

    plot_host = plot_panel.findChild(QFrame, "plotHost")
    if plot_host is None:
        print("  G5 FAIL: plotHost not found")
        return False

    # Create a PlotWidget and add it to plotHost (mirrors PlotView.__init__)
    try:
        ratio_plot = pg.PlotWidget(parent=plot_host, background="#F2F3F5")
        ratio_plot.setObjectName("ratioPlotWidget")
        ratio_plot.show()
    except Exception as exc:
        print(f"  G5 FAIL: PlotWidget creation failed: {exc}")
        return False

    # Verify it's a real widget with a PlotItem
    plot_item = ratio_plot.getPlotItem()
    if plot_item is None:
        print("  G5 FAIL: PlotWidget.getPlotItem() returned None")
        return False

    # Test basic curve creation
    try:
        curve = plot_item.plot([0, 1, 2], [0, 1, 0], pen=pg.mkPen("#0072B2", width=2))
    except Exception as exc:
        print(f"  G5 FAIL: curve creation failed: {exc}")
        return False

    # Cleanup
    ratio_plot.close()
    ratio_plot.deleteLater()

    print("  G5 INFO: PlotWidget created, PlotItem obtained, curve plotted successfully")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    window = TestMainWindow()
    window.show()

    gates = [
        ("G1: setattr attribute access", gate_g1),
        ("G2: findChild == setattr identity", gate_g2),
        ("G3: nested widget access + require_child targets", gate_g3),
        ("G4: QButtonGroup + idClicked", gate_g4),
        ("G5: pyqtgraph PlotWidget + curve creation", gate_g5),
    ]

    all_pass = True
    results = {}
    for label, func in gates:
        result = func(window)
        status = "PASS" if result else "FAIL"
        results[label] = status
        print(f"[{status}] {label}")
        if not result:
            all_pass = False

    # Extra info
    sb = window.statusBar()
    sb.showMessage("Spike test complete")
    print(f"\n[INFO] statusBar message: '{sb.currentMessage()}'")

    layout = window.centralWidget().layout()
    if isinstance(layout, QHBoxLayout):
        s0 = layout.stretch(0)
        s1 = layout.stretch(1)
        print(f"[INFO] centralLayout type=QHBoxLayout, stretch=({s0}, {s1})")
    else:
        ltype = type(layout).__name__ if layout else "None"
        print(f"[WARN] centralLayout type={ltype}")

    window.close()
    app.quit()

    print()
    if all_pass:
        print("=" * 50)
        print("  ALL GATES PASSED - C-plan confirmed")
        print("=" * 50)
        sys.exit(0)
    else:
        failed = [k for k, v in results.items() if v == "FAIL"]
        print("=" * 50)
        print(f"  GATES FAILED: {', '.join(failed)}")
        print("  Evaluate B-plan fallback (pyside6-uic composition)")
        print("=" * 50)
        sys.exit(1)


if __name__ == "__main__":
    main()
