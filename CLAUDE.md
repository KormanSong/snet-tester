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

- **All visual properties must live in `resources/ui/main_window.ui`**. Python code must only handle dynamic runtime state changes. What you see in Designer must match what runs.
- **Python에서 정적 UI 속성 설정 금지**: `setMinimumSize`, `setSizePolicy`, `setFont`, `setStyleSheet`(정적), `setContentsMargins`, `setSpacing` 등은 반드시 .ui 파일에 정의.
- **예외 시 주석 필수**: Python에서 불가피하게 UI 속성을 설정할 경우 `# ui-override: <사유>` 주석을 반드시 달 것. 주석 없는 정적 UI 설정은 위반.
- **허용되는 Python UI 설정**: 동적 상태 변경(dirty/clean 토글), Designer 미지원 속성(`setStretch`), Python 전용 위젯(pyqtgraph), 런타임 데이터 의존(`setText`).
- **검증 최우선**: 모든 UI 변경 후 Designer(`uv run snet-designer`)와 런타임(`--mock`)을 나란히 비교. 불일치 시 .ui 이관이 완료될 때까지 머지 금지.
- PlotView uses pyqtgraph with an ASM-inspired ivory gray background (#F2F3F5), industrial channel colors (Okabe-Ito based).
- Button labels use Korean 2-character convention (e.g., 저장/읽기), not English abbreviations.

## Key Constants (protocol/constants.py)

- `MAX_CHANNELS = 6`
- `RATIO_FULL_SCALE_RAW = 0x8000` → 100%
- Full-scale values for pressure, temperature, flow: 130.0
- `SAMPLE_PERIOD_S = 0.05` (50ms cycle)
- `FULL_OPEN_VALUE_SCALE = 1000`
