# PySide6 UI Loader Spike Results

## Environment

- Python: 3.13.12
- PySide6: 6.9.0
- pyqtgraph: 0.14.0
- numpy: 2.4.2
- OS: Windows 11 Pro 10.0.26200

## Gate Results

| Gate | Description | Result |
|------|-------------|--------|
| G1 | setattr attribute access after load_ui | **PASS** |
| G2 | findChild == setattr identity | **PASS** |
| G3 | Nested widget access + require_child targets (5/5 optional found) | **PASS** |
| G4 | QButtonGroup + idClicked signal | **PASS** |
| G5 | pyqtgraph PlotWidget + curve creation | **PASS** |

## Key Findings

1. **Custom QUiLoader wrapper works.** `_UiLoader.createWidget()` correctly returns
   the baseinstance for root widget requests and binds children via setattr.
2. **findChild and setattr are identity-equal** (same object), so require_child
   pattern works unchanged.
3. **All 5 optional rxPanel widgets found** (pressValueLabel, tempValueLabel,
   adCommandCheckBox, fullOpenControlCheckBox, fullOpenValueEdit).
4. **QButtonGroup.idClicked** correctly replaces PyQt5's `buttonClicked[int]`.
   Received signals: [1, 0] for CH1 and ALL clicks.
5. **pyqtgraph 0.14.0 auto-detects PySide6.** PlotWidget creation, PlotItem
   access, and curve plotting all work without code changes.
6. **centralLayout stretch (0, 0)** after load_ui. v1 sets stretch via Python
   code (main_window.py:167-169) with `setStretch(0, 5)` / `setStretch(1, 2)`.
   This is expected and documented as `# ui-override`.
7. **menuBar/statusBar** correctly handled by _UiLoader special-casing.
   `statusBar().showMessage()` works.

## Migration Notes

- `buttonClicked[int]` -> `idClicked` (Qt6 removed int overload)
- `from pyqtgraph.Qt import QtLib` -> `pg.Qt.QT_LIB` (attribute name changed)
- PySide6 6.9.0 is stable with pyqtgraph 0.14.0. Avoid 6.9.1 (known rendering issue).

## Decision

- [x] **C-plan confirmed** (custom QUiLoader wrapper)
- [ ] B-plan fallback not needed

## B-plan Fallback (if ever needed)

Use **composition** pattern only:
```python
from ui_main_window import Ui_MainWindow

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        # Access: self.ui.txPanel, self.ui.rxPanel, etc.
```
Do NOT mix with inheritance (`class MainWindow(QMainWindow, Ui_MainWindow)`).
