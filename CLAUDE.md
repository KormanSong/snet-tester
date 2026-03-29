# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

SNET Tester — a PyQt5 GUI application for testing SNET serial protocol communication with multi-channel flow controllers. Supports real-time graphing, preset management, Brooks KP calibration, and PID tuning.

## Commands

```bash
# Run (mock mode, no hardware needed)
python -m snet_tester --mock

# Run (real hardware)
python -m snet_tester --port COM6 --baud 115200

# Run tests
pytest

# Run single test file
pytest tests/test_codec.py -v

# Launch Qt Designer on the main .ui file
snet-designer

# Build standalone EXE (PowerShell)
./build_exe.ps1
```

Package manager is **uv**. Python version is 3.13.

## Architecture

**Threading model:** The UI thread and serial I/O run on separate threads, communicating through two queues:
- `_command_queue`: UI → SerialWorker (commands like `set_running`, `apply_setpoint`, `write_var`)
- `_event_queue`: SerialWorker → UI (events like `sample`, `rx_frame`, `error`)
- A 20ms QTimer on the UI thread drains the event queue and dispatches to panels.

**Layer separation:**
- `protocol/` — Pure data: frame codec, stream parser, unit conversion, constants. No Qt dependency.
- `comm/worker.py` — SerialWorker daemon thread: opens port, runs TX/RX loop, emits events.
- `views/` — PyQt5 panels (TxPanelView, RxPanelView, PlotView) that render state. No direct serial access.
- `views/main_window.py` — Central coordinator: wires worker events to panel updates, manages lifecycle.

**SNET frame format:** `[STX 0xA5 0x5A] [SEQ] [ID] [CH] [CMD 2B] [LEN] [PAYLOAD…]`

**Key data flow for a test cycle:**
1. TxPanelView builds `IoPayload` (channel ratios + mode)
2. MainWindow queues `apply_setpoint` command
3. SerialWorker encodes to frame, sends via serial, waits for response
4. Parser decodes response into `SnetMonitorSnapshot`
5. `sample` event emitted → MainWindow routes to RxPanelView (table) and PlotView (graph)

**Mock mode** (`--mock`): MainWindow generates synthetic samples on a timer, bypassing SerialWorker entirely. Useful for UI development.

## UI Development Rules — ABSOLUTE DIRECTIVE

> **P0 절대지침: Designer-Runtime UI 일치성**
> 상세: `docs/directive_ui_consistency.md`

### 원칙
- **All visual properties must live in `resources/ui/main_window.ui`**. Python code must only handle dynamic runtime state changes. What you see in Designer must match what runs.
- **검증 최우선**: 모든 UI 변경 후 Designer(`uv run snet-designer2`)와 런타임(`--mock`)을 나란히 비교. 불일치 시 .ui 이관이 완료될 때까지 머지 금지.
- PlotView uses pyqtgraph with an ASM-inspired ivory gray background (#F2F3F5), industrial channel colors (Okabe-Ito based).
- Button labels use Korean 2-character convention (e.g., 저장/읽기), not English abbreviations.

### views/ 수정 시 필수 체크리스트

**1. 새로 추가하는 정적 UI 속성이 있는가?**
`setMinimumSize`, `setSizePolicy`, `setFont`, `setStyleSheet`(정적), `setContentsMargins`, `setSpacing` 등
→ .ui에서 설정 가능하면 .ui에 추가. 불가능한 경우만 Python에서 설정 + 주석 필수.

**2. 새로 생성하는 위젯이 있는가?**
`QWidget()`, `QGroupBox()`, `QPushButton()` 등
→ `# ui-dynamic: <사유>` 주석 필수. .ui에 placeholder 배치를 먼저 고려.

**3. 기존 .ui 위젯을 교체/삭제하는 코드가 있는가?**
→ `# ui-dynamic: <사유>` 주석 + `docs/directive_ui_consistency.md`에 등록 필수.

### 분류 기준 (예외 체계)

| 분류 | 설명 | Python 허용 | 주석 |
|------|------|------------|------|
| **정적 속성** | 항상 같은 값 (font, margin, size) | **.ui에서만** | 금지 |
| **상태 기반 동적** | dirty/clean, RUN/STOP 전환 | Python 허용 | `# ui-override: <사유>` |
| **데이터 의존 동적** | setText, 테이블 아이템, 채널색 | Python 허용 | `# ui-dynamic: <사유>` |
| **Designer 미지원** | setStretch, pyqtgraph, 커스텀 위젯 | Python 필수 | `# ui-override: <사유>` + directive 등록 |
| **위젯 교체** | .ui 위젯을 다른 위젯으로 교체 | 최소화 | `# ui-dynamic: <사유>` + directive 등록 |

### 주석 형식
```python
# ui-override: <사유>  — .ui에서 설정 불가능한 속성 (예: setStretch, QHeaderView.Stretch)
# ui-dynamic: <사유>   — 런타임에만 존재하는 위젯/속성 (예: pyqtgraph, 동적 테이블 아이템)
```
**주석 없는 정적 UI 설정은 위반.** `tools/check_ui_consistency.py`로 자동 검사 가능.

## Key Constants (protocol/constants.py)

- `MAX_CHANNELS = 6`
- `RATIO_FULL_SCALE_RAW = 0x8000` → 100%
- Full-scale values for pressure, temperature, flow: 130.0
- `SAMPLE_PERIOD_S = 0.05` (50ms cycle)
- `FULL_OPEN_VALUE_SCALE = 1000`
