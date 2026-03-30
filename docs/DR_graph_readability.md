<!-- encoding: UTF-8 -->

# DR-2026-0330-001: Graph Readability Enhancement (Y-Axis Padding + Dotted Grid)

| Item            | Detail                                                    |
|-----------------|-----------------------------------------------------------|
| Document ID     | DR-2026-0330-001 rev.0                                    |
| Date            | 2026-03-30                                                |
| Author          | Architect (Graph Subsystem)                               |
| Submitted to    | Builder                                                   |
| Document type   | **Design Requirement Spec (DRS)**                         |
| Target module   | `snet_tester2/views/plot_view.py`                         |
| Priority        | Normal (Boss-approved UX enhancement)                     |
| Parent commits  | `68d6550` smooth graph transitions                        |

---

## 1. Purpose

그래프 가독성을 두 가지 축에서 개선한다:

1. **Y축 패딩**: 0%/100% 경계값 데이터가 축 프레임에 밀착되어 읽기 어려운 문제 해소
2. **격자선 점선화**: 실선 격자가 데이터 곡선과 시각적으로 경쟁하는 문제 해소

두 변경 모두 데이터 로직이나 프로토콜에 영향 없는 순수 표시(presentation) 계층 변경이다.

---

## 2. Functional Structure

### 2.1 Y-Axis Padding

| Plot    | Current Range  | New Range          | Padding | Tick Labels     |
|---------|----------------|--------------------|---------|-----------------|
| Ratio   | 0.0 ~ 100.0   | **-5.0 ~ 105.0**  | 5%      | 0,20,40,60,80,100 (unchanged) |
| Valve   | 0.0 ~ 5.0     | **-0.25 ~ 5.25**  | 5%      | 0,1,2,3,4,5 (unchanged)       |

변경 지점:

```python
# _configure_ratio_plot (현재)
plot.setYRange(0.0, 100.0, padding=0.0)
# _configure_ratio_plot (변경)
plot.setYRange(-5.0, 105.0, padding=0.0)

# _configure_valve_plot (현재)
plot.setYRange(0.0, 5.0, padding=0.0)
# _configure_valve_plot (변경)
plot.setYRange(-0.25, 5.25, padding=0.0)
```

근거: `padding=0.0` 유지하되 범위 자체를 확장하는 방식. pyqtgraph의 `padding` 파라미터를
사용하지 않는 이유는 padding이 적용된 실제 range가 내부적으로 불투명하여 테스트에서
검증이 어렵기 때문이다. 명시적 수치가 더 예측 가능하다.

### 2.2 Dotted Grid Lines

| Plot    | Current alpha | New alpha  | Line Style     |
|---------|---------------|------------|----------------|
| Ratio   | 0.25          | **0.40**   | `Qt.DotLine`   |
| Valve   | 0.15          | **0.40**   | `Qt.DotLine`   |

Alpha를 올리는 이유: DotLine은 픽셀 밀도가 낮아져 실선 대비 시인성이 떨어진다.
0.40으로 올려야 점선 격자가 "존재는 하되 데이터를 방해하지 않는" 균형점에 도달한다.

---

## 3. Module Responsibilities

### 3.1 New Function: `_patch_grid_to_dotline(axis: pg.AxisItem)`

| 항목      | 내용                                                        |
|-----------|-------------------------------------------------------------|
| 위치      | `plot_view.py` 모듈 수준 함수 (class 밖, `_patch_axis_bounding_rect` 근처) |
| 책임      | AxisItem.drawPicture를 래핑하여 grid line의 QPen style을 DotLine으로 변경 |
| 패턴      | 기존 `_patch_axis_bounding_rect`와 동일한 monkey-patch 패턴 |
| 재사용성  | axis 단위로 적용 가능 -- 향후 setpoint/판정선 강화 시에도 동일 패턴 사용 |

### 3.2 Function Signature

```python
def _patch_grid_to_dotline(axis: pg.AxisItem) -> None:
    """Patch drawPicture to render grid lines as dotted lines.

    Grid lines in pyqtgraph are drawn as regular tick lines extended to
    the full plot area. This patch intercepts drawPicture() and modifies
    the pen style of grid-extending ticks (those that span beyond the
    normal tick length) to Qt.DotLine before delegating to the original.

    Pattern: identical to _patch_axis_bounding_rect -- closure over
    original method, no subclassing, no generateDrawSpecs override.
    """
```

### 3.3 Patch Logic (Pseudocode)

```python
def _patch_grid_to_dotline(axis: pg.AxisItem) -> None:
    original_drawPicture = axis.drawPicture

    def _patched_drawPicture(p, axisSpec, tickSpecs, textSpecs):
        if axis.grid is not False:
            patched_specs = []
            for pen, p1, p2 in tickSpecs:
                new_pen = QtGui.QPen(pen)       # shallow copy
                new_pen.setStyle(QtCore.Qt.DotLine)
                patched_specs.append((new_pen, p1, p2))
            tickSpecs = patched_specs
        original_drawPicture(p, axisSpec, tickSpecs, textSpecs)

    axis.drawPicture = _patched_drawPicture
```

Grid가 켜져 있을 때(`axis.grid is not False`) tickSpecs의 모든 tick pen을
DotLine으로 변경한다. Grid가 꺼져 있으면 tick은 짧은 눈금선이므로 원래대로 둔다.

**핵심 판단**: grid 활성 시 tick과 grid line이 동일한 tickSpecs 리스트에 존재한다.
pyqtgraph AxisItem 소스(L1570-1572) 분석 결과, `self.grid is not False`일 때
tick의 p2가 tickStop(view boundary)까지 확장되고, `False`일 때만 tickLength만큼
짧은 눈금이 된다. 따라서 grid 활성 상태에서는 모든 tickSpecs 항목이 사실상
grid line이므로 전체를 DotLine으로 변환해도 정확하다.

### 3.4 Patch 호출 위치

`_synchronize_axis_geometry` 메서드에서 `_patch_axis_bounding_rect` 호출 직후:

```python
def _synchronize_axis_geometry(self):
    for plot, margin in ((self._ratio_plot, 30), (self._valve_plot, 50)):
        for name in ('left', 'bottom'):
            axis = plot.getAxis(name)
            axis.setStyle(...)
            _patch_axis_bounding_rect(axis)
            _patch_grid_to_dotline(axis)       # <-- NEW
        plot.getAxis('left').setWidth(LEFT_AXIS_WIDTH_PX)
```

---

## 4. Data Flow

변경 없음. 이 DRS는 표시 계층만 건드린다.

```
SerialWorker --> event queue --> add_point() --> _build_display_data() --> setData()
                                                                            |
                                                        pyqtgraph rendering pipeline
                                                            |
                                        AxisItem.generateDrawSpecs() -> tickSpecs
                                            |
                                        AxisItem.drawPicture()  <-- PATCHED (DotLine)
                                            |
                                        QPainter.drawLine()
```

Y축 범위 변경은 `setYRange` 호출 시점(PlotView 초기화)에 완료되며,
이후 데이터 흐름에 영향 없다.

---

## 5. Change Summary

| File                               | Change                                    | Lines  |
|------------------------------------|-------------------------------------------|--------|
| `snet_tester2/views/plot_view.py`  | `_patch_grid_to_dotline()` 함수 추가       | ~15    |
| `snet_tester2/views/plot_view.py`  | `_synchronize_axis_geometry`에 호출 추가    | +1     |
| `snet_tester2/views/plot_view.py`  | `_configure_ratio_plot`: alpha 0.25->0.40, Y range 변경 | 2 lines |
| `snet_tester2/views/plot_view.py`  | `_configure_valve_plot`: alpha 0.15->0.40, Y range 변경 | 2 lines |
| `tests/test_v2_plot_view.py`       | Y range 패딩 검증 테스트 추가              | ~15    |
| `tests/test_v2_plot_view.py`       | DotLine 패치 검증 테스트 추가              | ~20    |

### Not Changed

- `protocol/` layer: no data model changes
- `comm/worker.py`: no communication changes
- `.ui` file: no layout changes
- Curve rendering logic (`_build_display_data`, `refresh`): untouched
- Tick label values: unchanged

---

## 6. Error / Edge Case Handling

| Case                                  | Handling                                  |
|---------------------------------------|-------------------------------------------|
| Grid disabled (`showGrid(x=False, y=False)`) | `axis.grid is False` -> 패치가 원본 그대로 위임, DotLine 미적용 |
| tickSpecs 빈 리스트                   | 빈 리스트 순회 -> no-op, 원본 drawPicture 정상 호출 |
| QPen copy 실패                        | 발생 불가 (QPen(pen)은 Qt 표준 copy constructor) |
| Y range 밖 데이터                     | 기존과 동일 -- 범위 밖 데이터는 클리핑됨. 패딩 영역(-5~0, 100~105)에 데이터가 진입하면 정상 표시 |
| `_patch_grid_to_dotline` 중복 호출    | 기존 `_patch_axis_bounding_rect`와 동일 -- closure가 이전 패치를 감싸므로 기능적 무해하나, 1회만 호출하도록 설계 |

---

## 7. Test / Verification Points

### 7.1 Automated Tests (pytest)

| Test Name                           | Verification                              |
|-------------------------------------|-------------------------------------------|
| `test_ratio_y_range_has_padding`    | `_ratio_plot.viewRange()[1]` == [-5.0, 105.0] |
| `test_valve_y_range_has_padding`    | `_valve_plot.viewRange()[1]` == [-0.25, 5.25] |
| `test_grid_dotline_patch_applied`   | Ratio/Valve left/bottom axis의 `drawPicture`가 패치됨 (original과 다른 함수 참조) |
| `test_grid_dotline_pen_style`       | 패치된 `drawPicture` 호출 시 tickSpecs의 pen.style()이 `Qt.DotLine` |

### 7.2 Manual Verification

| Step | Action                                  | Expected Result                        |
|------|-----------------------------------------|----------------------------------------|
| 1    | `uv run python -m snet_tester2 --mock`  | 그래프 정상 표시                       |
| 2    | Ratio 플롯 Y축 확인                     | 0% 라인 아래/100% 라인 위에 여백 존재  |
| 3    | Valve 플롯 Y축 확인                     | 0V 라인 아래/5V 라인 위에 여백 존재    |
| 4    | 격자선 육안 확인                         | 점선(dotted), 데이터 곡선보다 약함     |
| 5    | Tick 라벨 확인                           | 0,20,40,60,80,100 / 0,1,2,3,4,5 동일  |
| 6    | `uv run snet-designer2`                 | .ui 파일 변경 없으므로 Designer 확인 불필요 |

### 7.3 Existing Test Regression

| Existing Test                        | Impact                                    |
|--------------------------------------|-------------------------------------------|
| `test_leading_edge_advances`         | No change (data logic untouched)          |
| `test_hold_ramp_in_set_data`         | No change (curve rendering untouched)     |
| `test_ramp_points_inserted`          | No change (data expansion untouched)      |
| `test_wrap_boundary_no_cross_cycle`  | No change (buffer logic untouched)        |
| `test_nan_channel_no_leading_edge`   | No change (NaN logic untouched)           |
| `test_refresh_throttle`              | No change (throttle logic untouched)      |

---

## 8. Design Decisions and Trade-offs

### 8.1 Why drawPicture Patch (not generateDrawSpecs Override)?

| Approach               | Pros                        | Cons                          | Verdict    |
|------------------------|-----------------------------|-------------------------------|------------|
| **drawPicture patch**  | Minimal touch, pen-only change, same pattern as existing `_patch_axis_bounding_rect` | Iterates tickSpecs each paint (negligible cost) | **Selected** |
| generateDrawSpecs override | Could filter grid vs tick lines separately | Deeply coupled to pyqtgraph internals (40+ local vars), fragile on version upgrade | **Rejected** |
| Custom GridItem        | Full control                | Duplicates pyqtgraph axis grid logic, maintenance burden | **Rejected** |

Boss 지시 "generateDrawSpecs 오버라이드 금지"에 부합한다.

### 8.2 Why All tickSpecs Get DotLine (Not Selective)?

pyqtgraph AxisItem L1570-1572 분석:

```python
if self.grid is False:
    p2[axis] += tickLength*tickDir    # short tick mark
# else: p2 stays at tickStop (full grid line)
```

Grid 활성 시 모든 tick이 plot boundary까지 확장된다 -- 즉 "짧은 눈금"은 존재하지 않고
전부 grid line이다. 따라서 선택적 필터링이 불필요하다.

### 8.3 Reusability for Future Enhancement

`_patch_grid_to_dotline`은 axis 단위로 독립 적용된다:

- 향후 setpoint 판정선 overlay 추가 시, 해당 axis에만 다른 스타일 적용 가능
- 함수 시그니처를 `_patch_grid_to_dotline(axis, style=Qt.DotLine)`로 확장하면
  DashLine, DashDotLine 등도 동일 패턴으로 지원 가능
- 현재는 YAGNI 원칙에 따라 `Qt.DotLine` 하드코딩. 확장은 필요 시점에 수행

### 8.4 Limitation

- pyqtgraph 내부 `drawPicture` 시그니처가 변경되면 패치가 깨진다.
  현재 pyqtgraph 0.13.x 기준. 버전 업그레이드 시 `_patch_axis_bounding_rect`와
  함께 검증 필요.

---

| Review      | Signature | Date       |
|-------------|-----------|------------|
| Architect   | --        | 2026-03-30 |
| Builder     |           |            |
| Boss        |           |            |
