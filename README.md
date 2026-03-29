# SNET Protocol Tester

A PySide6 (Qt6) GUI application for testing **SNET serial protocol** communication with multi-channel flow controllers.

## Features

- **6-channel flow control** with real-time ratio setpoint management
- **Dual real-time graphs** — ratio (%) and valve (V) with 10-second rolling window
- **Preset management** — save, load, and apply channel ratio presets
- **Brooks KP calibration** — read/write KP coefficients via relay channel
- **PID tuning** — KP/KI/KD parameter editing with dirty-state tracking
- **Variable read/write** — AD command, full-open control, mode toggle (RUN/CAL)
- **Mock mode** — full UI testing without hardware (`--mock` flag)
- **Fault injection testing** — 9 fault types (timeout, corrupt, disconnect, etc.) via MockTransport

## Architecture

```
snet_tester2/
  protocol/     Pure data layer — frame codec, parser, types, enums, conversions (no Qt)
  transport/    Transport abstraction — SerialTransport, MockTransport with fault injection
  comm/         Worker thread — typed events/commands via SimpleQueue, Transport-agnostic
  state/        Statistics (Welford online mean/variance)
  views/        PySide6 UI — MainWindow, TxPanel, RxPanel, PlotView
  resources/    Qt Designer .ui file + presets.json
```

**Key design decisions:**
- **Transport Protocol** (`typing.Protocol`) — serial and mock share the same interface; worker has zero mock-specific code
- **Typed events/commands** — frozen dataclasses replace string tuples for type safety
- **Designer-first UI** — all static visual properties live in `.ui`; Python handles only dynamic state changes
- **Qt6 native style** — `windows11` style with forced `Light` color scheme for consistent rendering

## Quick Start

### Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager

### Install & Run

```bash
# Install dependencies
uv sync

# Run in mock mode (no hardware needed)
uv run python -m snet_tester2 --mock

# Run with real hardware
uv run python -m snet_tester2 --port COM6 --baud 115200

# Launch Qt Designer
uv run snet-designer2

# Run tests
uv run pytest

# UI consistency check
uv run python tools/check_ui_consistency.py --strict
```

## SNET Frame Format

```
[STX 0xA5 0x5A] [SEQ] [ID] [CH] [CMD 2B] [LEN] [PAYLOAD...]
```

| Command | Code | Description |
|---------|------|-------------|
| IO_REQUEST | `0x8000` | Send channel ratios, receive monitor data |
| IO_RESPONSE | `0x8100` | Monitor response (AD, flow, ratio, valve per channel) |
| READ_VAR | `0x0001` | Read device variable |
| WRITE_VAR | `0x0002` | Write device variable |
| BROOKS_GET_KP | `0x104C` | Read KP calibration coefficients |

## Testing

177 tests covering protocol codec, transport fault injection, worker integration, oracle parity, PySide6 smoke tests, and UI consistency.

```bash
# Full test suite
uv run pytest -v

# Specific layers
uv run pytest tests/test_v2_codec.py tests/test_v2_parser.py       # protocol
uv run pytest tests/test_v2_transport_mock.py                       # fault injection (30 tests)
uv run pytest tests/test_v2_worker.py                               # worker integration
uv run pytest tests/test_v2_pyside6_smoke.py                        # PySide6 porting
uv run pytest tests/test_v2_response_tracker.py                     # response time tracker
```

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `snet_tester2/` | v2 application (PySide6) — primary |
| `snet_tester/` | v1 legacy (PyQt5) — hybrid, uses v2 core |
| `tests/` | 177 tests (protocol, transport, worker, views, oracle) |
| `tools/` | `check_ui_consistency.py` — automated Designer-Runtime consistency gate |
| `docs/` | `directive_ui_consistency.md` — P0 UI consistency directive |
| `spike/` | PySide6 QUiLoader spike (completed) |

## UI Consistency (P0 Directive)

All static visual properties must be defined in the `.ui` file. Python code handles only dynamic state changes. Exceptions require `# ui-override:` or `# ui-dynamic:` annotations.

Automated enforcement: `tools/check_ui_consistency.py` runs as a pytest gate (0 violations required).

## License

Proprietary — SNET Protocol Tester for industrial flow controller testing.
