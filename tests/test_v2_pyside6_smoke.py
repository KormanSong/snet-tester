"""PySide6 view layer smoke tests — verifies critical porting points.

Tests require a QApplication instance (created via qapp fixture).
Each test validates a specific PyQt5→PySide6 porting risk:
  - Custom QUiLoader wrapper (load_ui + require_child)
  - MainWindow creation with mock transport
  - pyqtgraph PlotWidget on PySide6
  - Property decorator for animation
  - QButtonGroup idClicked signal
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QButtonGroup


@pytest.fixture(scope="module")
def qapp():
    """Provide a QApplication instance for the test module."""
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_creates(qapp):
    """MainWindow with mock_mode creates without error, panels exist."""
    from snet_tester2.views.main_window import MainWindow
    w = MainWindow(mock_mode=True)
    assert w.tx_panel is not None
    assert w.rx_panel is not None
    assert w.plot_view is not None
    w.shutdown()
    w.close()


def test_load_ui_binds_children(qapp):
    """Custom QUiLoader wrapper binds .ui children as attributes."""
    from snet_tester2.views.main_window import MainWindow
    w = MainWindow(mock_mode=True)
    # These are require_child targets from MAIN_WINDOW_OBJECTS
    assert w.findChild(QWidget, 'txPanel') is not None
    assert w.findChild(QWidget, 'rxPanel') is not None
    assert w.findChild(QWidget, 'plotPanel') is not None
    assert w.findChild(QWidget, 'debugTabWidget') is not None
    # Verify setattr binding matches findChild
    assert getattr(w, 'txPanel', None) is w.findChild(QWidget, 'txPanel')
    w.shutdown()
    w.close()


def test_pyqtgraph_plot_widget(qapp):
    """pyqtgraph PlotWidget creates and renders curves on PySide6."""
    import pyqtgraph as pg
    pw = pg.PlotWidget(background='#F2F3F5')
    item = pw.getPlotItem()
    assert item is not None
    curve = item.plot([0, 1, 2], [0, 1, 0], pen=pg.mkPen('#0072B2', width=2))
    assert curve is not None
    pw.close()


def test_property_decorator(qapp):
    """_ModeToggleSwitch's Property(float) works for QPropertyAnimation."""
    from snet_tester2.views.tx_panel import _ModeToggleSwitch
    toggle = _ModeToggleSwitch()
    # Property should be accessible
    assert hasattr(toggle, 'thumbPosition')
    # Should be a float
    pos = toggle.property('thumbPosition')
    assert isinstance(pos, (int, float))
    toggle.close()


def test_button_group_id_clicked(qapp):
    """QButtonGroup.idClicked signal fires with correct ID (PySide6 Qt6 API)."""
    group = QButtonGroup()
    group.setExclusive(True)
    btn_a = QPushButton("A")
    btn_b = QPushButton("B")
    group.addButton(btn_a, 10)
    group.addButton(btn_b, 20)

    received = []
    group.idClicked.connect(lambda id_: received.append(id_))

    btn_a.click()
    assert received == [10]
    btn_b.click()
    assert received == [10, 20]
