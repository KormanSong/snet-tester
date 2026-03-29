# P0 절대지침: Designer-Runtime UI 일치성

> **등급**: P0 — 모든 Phase, 모든 작업에서 최우선 준수
> **제정일**: 2026-03-28
> **적용 범위**: `snet_tester2/views/*.py`, `snet_tester2/resources/ui/*.ui`

---

## 원칙

**Qt Designer에서 보이는 화면과 런타임 프로그램의 화면은 반드시 일치해야 한다.**

- 정적 UI 속성은 오직 `.ui` 파일에서만 정의한다.
- Python 코드는 동적 상태 변경과 Designer 미지원 기능에만 사용한다.
- 모든 예외는 주석과 이 문서의 등록을 통해 추적한다.

---

## 분류 기준

| 분류 | 설명 | Python 허용 | 주석 |
|------|------|------------|------|
| **정적 속성** | 항상 같은 값 (크기, 여백, 폰트, 정적 스타일) | `.ui`에서만 | 금지 — 위반 시 `.ui` 이관 |
| **상태 기반 동적** | dirty/clean, RUN/STOP 토글 등 | Python 허용 | `# ui-override: <사유>` |
| **데이터 의존 동적** | `setText`, 채널색, 테이블 아이템 생성 | Python 허용 | `# ui-dynamic: <사유>` |
| **Designer 미지원** | `setStretch`, `QHeaderView.setSectionResizeMode`, pyqtgraph | Python 필수 | `# ui-override: Designer 미지원` + 등록 |
| **위젯 교체** | `.ui` placeholder → 커스텀 위젯 교체 | 최소화 | `# ui-dynamic: <사유>` + 등록 |

---

## 주석 형식

### `# ui-override: <사유>`

Designer에 정의할 수 없는 속성을 Python에서 설정할 때 사용한다.
주석이 없는 정적 UI 속성 설정은 위반으로 간주한다.

```python
# ui-override: Designer 미지원 — QSplitter stretch ratio
central_layout.setStretch(0, 5)
central_layout.setStretch(1, 2)
```

### `# ui-dynamic: <사유>`

런타임 데이터나 조건에 의존하는 위젯 생성/변경에 사용한다.

```python
# ui-dynamic: 채널색(Okabe-Ito) 런타임 계산
btn.setStyleSheet(f"background-color: {channel_color};")
```

---

## 알려진 위반/면제 사항

| 함수/위치 | objectName | 분류 | 상태 |
|-----------|-----------|------|------|
| `MainWindow.__init__` | centralLayout | ui-override | Designer 미지원 — `setStretch` |
| `MainWindow._build_calibration_group` | calibrationGroup | ui-dynamic | **EXEMPT** — `.ui` 이관 대상, 별도 ECR 추적 |
| `MainWindow._build_calibration_group` | calibrationScrollArea | ui-dynamic | **EXEMPT** — calibrationGroup 내부 |
| `PlotView._build_plots` | ratioPlotWidget, valvePlotWidget | ui-override | Python 전용 위젯 (pyqtgraph) |
| `PlotView._build_plots` | plotHost layout | ui-override | Designer 미지원 — `QVBoxLayout` stretch |
| `PlotView._configure_toggle_buttons` | legendTx*Button, legendRx*Button | ui-dynamic | 채널색(Okabe-Ito) 런타임 계산 |
| `TxPanelView._upgrade_mode_toggle` | modeToggle | ui-dynamic | Designer 미지원 커스텀 위젯 교체 |
| `TxPanelView._init_preset_table` | presetTable | ui-override | Designer 미지원 — per-column `ResizeMode` |
| `TxPanelView._add_preset_row` | preset APPLY 버튼 | ui-dynamic | 행 수 런타임 결정 |
| `TxPanelView._configure_frame_table` | txFrameTable header | ui-override | Designer 미지원 — `QHeaderView.Stretch` |
| `RxPanelView._configure_monitor_table` | rxMonitorTable items | ui-dynamic | 테이블 아이템 런타임 생성 |
| `RxPanelView._configure_monitor_table` | rxMonitorTable header | ui-override | Designer 미지원 — `QHeaderView.Stretch` |
| `RxPanelView._configure_frame_table` | rxFrameTable header | ui-override | Designer 미지원 — `QHeaderView.Stretch` |
| `helpers.build_fixed_font` | (전역) | ui-override | 시스템 고정폭 폰트 런타임 결정 |
| `helpers.set_badge` | plot*ValueLabel 등 | ui-dynamic | 상태 배지 색상 동적 변경 |

---

## 검증 절차

1. `views/` 수정 후 `check_ui_consistency.py` 실행
2. Designer(`uv run snet-designer2`) vs Runtime(`uv run python -m snet_tester2 --mock`) 나란히 비교
3. 불일치 항목 발견 시 `.ui` 이관 또는 `# ui-override:` 주석 추가
4. 새 면제 사항은 반드시 이 문서의 "알려진 위반/면제 사항" 테이블에 등록

---

## 변경 이력

| 날짜 | 변경 |
|------|------|
| 2026-03-28 | 초판 작성 — 원칙, 규칙, 알려진 위반 사항, 검증 프로세스 |
| 2026-03-28 | ECR-2026-001: 줄 번호 → 함수명/objectName 기반 전환, 분류 체계 추가 |
