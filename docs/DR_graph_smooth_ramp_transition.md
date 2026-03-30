<!-- encoding: UTF-8 -->

# DR-2026-0329-001: Graph Transition Style - Supplementary Change Proposal

| Item              | Detail                                                     |
|-------------------|------------------------------------------------------------|
| Document ID       | DR-2026-0329-001 rev.2                                     |
| Date              | 2026-03-29                                                 |
| Author            | PL (Graph Subsystem Team)                                  |
| Submitted to      | PM                                                         |
| Document type     | **Supplementary change proposal** (not ECR closure report) |
| Parent ECR commit | `68d6550` feat: smooth graph update with step-style transitions |
| Target module     | `snet_tester2/views/plot_view.py`                          |
| Priority          | Normal (UX enhancement inquiry)                            |

---

## 1. Background and Document Scope

### 1.1 Approved ECR (68d6550) - Already Implemented

Commit `68d6550` implemented the following changes per the approved ECR:

| Change                       | Detail                                              |
|------------------------------|-----------------------------------------------------|
| Refresh rate                 | `GRAPH_REFRESH_S` 50ms -> 20ms (~50fps visual)      |
| Leading edge rendering       | Extends last value to current time between samples   |
| Step mode standardization    | `stepMode='left'` applied to all RX and valve curves |
| Regression tests             | 5 tests added (`tests/test_v2_plot_view.py`)         |

**The approved direction**: smooth forward progression (leading edge) with
step-style value transitions. This is fully implemented and operational.

### 1.2 This Document's Purpose

The customer subsequently asked:

> "Is there a way to connect previous graph segments diagonally
> for a smoother appearance?"
> (Original: "ige-jeon graph-e daehaeseoneun daegakseon-euro ieo
> budeureobge boyeojuneun bang-an-i jonjaehapnikka?")

This is a **feasibility inquiry**, not a change request. The customer
confirmed that step-style value transitions are acceptable. The diagonal
connection was posed as a question ("does a method exist?"), not a
requirement.

**This document evaluates whether the diagonal (ramp) approach offers
meaningful improvement over the approved step-based solution, and under
what conditions it would be worth pursuing.**

### 1.3 Customer's Stated Priorities (Restated for Clarity)

| Priority | Requirement                                    | Status       |
|----------|------------------------------------------------|--------------|
| P0       | Graph progresses smoothly forward in real-time | Done (ECR)   |
| P1       | Previous value holds until new sample arrives  | Done (ECR)   |
| P2       | Step-style value transitions are acceptable    | Done (ECR)   |
| P3       | Diagonal connection between values (inquiry)   | **This DR**  |

---

## 2. Current State (As-Is) After ECR Implementation

### 2.1 Architecture

```
SerialWorker (50ms sample) --> event queue --> UI Timer (20ms)
    --> add_point() --> _build_display_data() --> leading edge extension
    --> setData(connect='finite', stepMode='left')
```

- Buffer: 200 points (10s window / 50ms), circular, NaN-filled
- Curves: up to 18 (6ch x TX/RX/Valve)
- Leading edge: `_build_display_data()` appends one extra point at
  `last_x + elapsed_frac * SAMPLE_PERIOD_S` with `y = last_value`

### 2.2 Visual Behavior (Current)

```
Value(%)
 70 |          +------------    <-- instant vertical jump (step)
    |          |
 50 |----------+
    +------------------------> Time(s)
     0.00     0.05    0.10

Between samples, the leading edge extends the last value forward
smoothly at ~50fps. Value changes appear as instant vertical steps.
```

### 2.3 Key Code References

| Location                        | Function                        |
|---------------------------------|---------------------------------|
| `plot_view.py` L293, L298, L313 | Curve creation with stepMode    |
| `plot_view.py` L568-594         | `_build_display_data()` + leading edge |
| `plot_view.py` L596-612         | `refresh()` with setData calls  |
| `tests/test_v2_plot_view.py` L83-107 | stepMode='left' verification test |

---

## 3. Feasibility Analysis: Hold+Ramp Approach

### 3.1 pyqtgraph Built-in Options Investigation

| Option       | Available modes                          | Smooth transition? |
|--------------|------------------------------------------|--------------------|
| `stepMode`   | `'left'`, `'right'`, `'center'`          | No                 |
| `connect`    | `'all'`, `'pairs'`, `'finite'`, ndarray  | No (on/off only)   |
| `antialias`  | True/False                               | Aliasing only      |
| QPainterPath | moveTo / lineTo                          | No curves          |

**Conclusion: No built-in smooth-step mode exists in pyqtgraph.**
Any ramp/diagonal transition must be implemented at the data level.

### 3.2 Data-Level Hold+Ramp Technique

Remove `stepMode='left'` and manually insert hold+ramp points in
`_build_display_data()`:

```
Original:   (t0, v0),  (t1, v1),  (t2, v2)

Expanded:   (t0, v0) --- (t1-d, v0) / (t1, v1) --- (t2-d, v1) / (t2, v2)
            ~~~~~~hold~~~~~~  ramp  ~~~~~~hold~~~~~~  ramp

            d = SAMPLE_PERIOD_S * RAMP_FRAC
```

- `RAMP_FRAC` controls diagonal duration as fraction of sample period
- N original points -> 2N expanded points (same as stepMode internal expansion)
- `connect='finite'` preserved for NaN gap handling

### 3.3 Approaches Evaluated

| #  | Approach                   | Visual  | Perf   | Complexity | Past data | Verdict      |
|----|----------------------------|---------|--------|------------|-----------|--------------|
| 1  | Data-level Hold+Ramp       | Good    | Low    | Medium     | Yes       | Feasible     |
| 2  | Smoothstep interpolation   | V.Good  | Medium | High       | Yes       | Overkill     |
| 3  | pyqtgraph built-in         | --      | --     | --         | --        | Not possible |
| 4  | QTimer sub-interval anim   | Good*   | High   | High       | No        | Rejected     |

*Approach 4 rejected: 18 concurrent animation timers, no effect on
scrolled-back data, conflicts with existing leading-edge logic.

---

## 4. Comparison: Approved Step vs Proposed Ramp

### 4.1 Side-by-Side Visual

**Option A: Current (Step) - Approved ECR**
```
Value(%)
 70 |          +------------
    |          |
 50 |----------+
    +------------------------> Time(s)
     0.00     0.05    0.10
```
- Clear, unambiguous value transitions
- Consistent with industrial control system conventions
- No information loss at transition boundaries

**Option B: Proposed (Hold+Ramp)**
```
Value(%)
 70 |            /----------
    |           /
 50 |---------/
    +------------------------> Time(s)
     0.00  0.0375  0.05  0.10

     RAMP_FRAC = 0.25 -> 12.5ms diagonal, 37.5ms hold
```
- Softer visual transition
- Introduces ambiguity: during the 12.5ms ramp, the displayed value
  is between old and new (not a real measurement)

### 4.2 Quantitative Comparison

| Metric                         | Option A (Step)  | Option B (Ramp)   |
|--------------------------------|------------------|-------------------|
| Data fidelity                  | Exact            | Interpolated during ramp |
| Transition duration            | 0ms (instant)    | 12.5ms (RAMP_FRAC=0.25) |
| Points per sample              | N -> 2N (internal) | N -> 2N (manual) |
| setData call overhead          | Equivalent       | Equivalent        |
| Memory delta                   | N+1 (lead edge)  | 2N+1 (+800B max)  |
| CPU impact                     | Baseline         | +numpy expand (~0.01ms) |
| Test changes required          | None             | 2 tests updated   |
| Code changes                   | None             | 1 function + 3 call sites |
| Existing regression test count | 5 pass           | 2 need update, 3 unchanged |

### 4.3 Risk Assessment

| Risk                              | Impact   | Likelihood | Mitigation              |
|-----------------------------------|----------|------------|-------------------------|
| Ramp shows non-real intermediate values | Data trust | Medium | Document as visual-only interpolation |
| Customer expects step (approved)  | Scope    | Low        | Confirm with customer before implementing |
| NaN boundary produces spurious diagonal | Display | Low   | `connect='finite'` handles automatically |
| Existing test_step_mode_in_set_data fails | Test | Certain | Update test to verify ramp behavior |
| RAMP_FRAC too small = no visible difference | UX | Low  | Tunable constant, verify with --mock |

---

## 5. Acceptance Criteria (If Ramp Proposal Is Approved)

### 5.1 Functional Criteria

| ID    | Criterion                                              | Method            |
|-------|--------------------------------------------------------|-------------------|
| AC-01 | Leading edge still extends last value at ~50fps        | `--mock` visual   |
| AC-02 | Value transitions show diagonal ramp (not vertical)    | `--mock` visual   |
| AC-03 | Hold duration >= 75% of sample period (37.5ms at 50ms) | Code review (RAMP_FRAC <= 0.25) |
| AC-04 | NaN channels produce no spurious lines                 | test_nan_channel_no_leading_edge |
| AC-05 | Buffer wrap produces no cross-cycle artifacts           | test_wrap_boundary_no_cross_cycle |
| AC-06 | Refresh throttle behavior unchanged                    | test_refresh_throttle |
| AC-07 | All 6 channels render correctly with ramp              | `--mock` visual (6ch) |

### 5.2 Performance Criteria

| ID    | Criterion                                   | Method                  |
|-------|---------------------------------------------|-------------------------|
| PC-01 | refresh() duration < 2ms (18 curves)        | time.perf_counter probe |
| PC-02 | No visible frame drops at 20ms refresh      | `--mock` 60s run        |
| PC-03 | Memory usage delta < 5KB vs current         | Process monitor         |

### 5.3 Test Plan

| Existing test                          | Impact                              |
|----------------------------------------|-------------------------------------|
| test_leading_edge_advances             | No change (leading edge preserved)  |
| test_step_mode_in_set_data             | **Update**: verify stepMode absent, verify ramp points present |
| test_wrap_boundary_no_cross_cycle      | No change (NaN isolation preserved) |
| test_nan_channel_no_leading_edge       | No change (NaN logic preserved)     |
| test_refresh_throttle                  | No change (throttle logic untouched)|

New test to add:
- `test_ramp_points_inserted`: verify that `_build_display_data()` output
  contains hold+ramp points when consecutive values differ

---

## 6. Implementation Outline (Contingent on Approval)

### 6.1 Changes Required

| File                          | Change                              | Lines affected |
|-------------------------------|-------------------------------------|----------------|
| `snet_tester2/views/plot_view.py` | Add `RAMP_FRAC` constant       | +1 (new)       |
| `snet_tester2/views/plot_view.py` | Modify `_build_display_data()`  | ~30 lines      |
| `snet_tester2/views/plot_view.py` | Remove `stepMode='left'` from `refresh()` | 3 call sites |
| `snet_tester2/views/plot_view.py` | Remove `stepMode='left'` from `_build_plots()` | 3 call sites |
| `tests/test_v2_plot_view.py`  | Update stepMode test + add ramp test | ~25 lines  |

### 6.2 Not Changed

- `protocol/` layer: no data model changes
- `comm/worker.py`: no communication changes
- `SAMPLE_PERIOD_S`: protocol timing unchanged (UI presentation only)
- `.ui` file: no layout changes
- Leading edge mechanism: preserved as-is

---

## 7. Recommendation

### Assessment

The Hold+Ramp approach is **technically feasible** with minimal risk and
negligible performance impact. However:

1. **The approved ECR already satisfies the customer's stated P0-P2
   requirements.** Step-style transitions were explicitly accepted.

2. The customer's diagonal inquiry (P3) was phrased as a question,
   not a request. It may be satisfied by confirming that the option
   exists and can be implemented if desired.

3. Ramp introduces interpolated (non-real) values during transitions,
   which may conflict with industrial monitoring conventions where
   displayed values should reflect actual measurements.

### Proposed Next Steps

| Option | Action                                           | Effort  |
|--------|--------------------------------------------------|---------|
| A      | Reply to customer: "Feasible. Current step approach is recommended for data fidelity. Ramp available on request." | None |
| B      | Implement ramp with `RAMP_FRAC=0.25`, deliver as optional mode | 0.5 day |
| C      | Implement ramp as default, keep step as fallback (`RAMP_FRAC=0.0`) | 0.5 day |

**PL recommendation: Option A** (respond to inquiry, defer implementation
unless customer explicitly requests it).

If PM decides Option B or C, implementation can begin immediately per
Section 6 outline.

---

## Delta Rev.2 — SET(TX) Step 복원 및 RX/Valve 전체 보간 적용

| Item           | Detail                                                          |
|----------------|-----------------------------------------------------------------|
| Delta ID       | DR-2026-0329-001 **rev.2**                                      |
| Date           | 2026-03-30                                                      |
| Label          | 고객사 요청에 따른 표시용 보간                                  |
| Change scope   | `snet_tester2/views/plot_view.py` — curve transition constants  |

### D1. Change Summary

| Curve group   | Before (rev.1 proposal)                | After (rev.2)                           |
|---------------|----------------------------------------|-----------------------------------------|
| SET (TX)      | `stepMode='left'` removed, Hold+Ramp with `RAMP_FRAC=0.25` proposed | **`stepMode='left'` restored** (pure step) |
| RX (measured) | Same as TX (`RAMP_FRAC=0.25`)          | Hold+Ramp with **`RAMP_FRAC_RX=1.0`** (full diagonal) |
| Valve         | Same as TX (`RAMP_FRAC=0.25`)          | Hold+Ramp with **`RAMP_FRAC_RX=1.0`** (full diagonal) |

**Visual**:

```
SET (TX) — pure step (unchanged from ECR):

Value(%)
 70 |          +------------
    |          |
 50 |----------+
    +------------------------> Time(s)


RX / Valve — full diagonal (RAMP_FRAC_RX = 1.0):

Value(%)
 70 |              /-----------
    |             /
 50 |-----------/
    +------------------------> Time(s)
     0.00      0.05     0.10

    Entire sample interval is ramp. No hold segment.
```

### D2. Requirement Change History

| Rev  | Decision                                    | Rationale                                      |
|------|---------------------------------------------|------------------------------------------------|
| ECR  | `stepMode='left'` for all curves            | Semantic accuracy: values hold until next sample |
| rev.1 | Proposed `RAMP_FRAC=0.25` for all curves   | PL feasibility assessment for diagonal inquiry  |
| **rev.2** | TX: step restored, RX/Valve: `RAMP_FRAC_RX=1.0` | Customer explicitly requested diagonal for measured values. TX remains step because SET is an instantaneous command value — diagonal would misrepresent the command semantics. |

Customer's explicit direction (paraphrased):

> "Measured values (RX, Valve) should be connected diagonally for readability.
> SET values are command inputs and should remain as step transitions."

This upgrades the diagonal connection from a P3 inquiry (rev.1 Section 1.2)
to a **confirmed customer requirement** for RX/Valve curves only.

### D3. Constants

| Constant (rev.1)  | Constant (rev.2)     | Value   | Applies to     |
|--------------------|----------------------|---------|----------------|
| `RAMP_FRAC = 0.25` (proposed) | **removed** | --  | --             |
| --                 | **`RAMP_FRAC_RX`**   | `1.0`   | RX + Valve curves only |

- No TX ramp constant is needed. TX curves use `stepMode='left'` directly.
- `RAMP_FRAC_RX = 1.0` means the entire sample interval is a diagonal ramp
  with no horizontal hold segment before the transition.
- The constant lives in `plot_view.py` alongside `GRAPH_REFRESH_S` and
  `SAMPLE_PERIOD_S` references.

### D4. Implementation Delta from Rev.1 Section 6

| File                               | Rev.1 planned change                     | Rev.2 actual change                                  |
|------------------------------------|------------------------------------------|-------------------------------------------------------|
| `plot_view.py` — `_build_plots()`  | Remove `stepMode='left'` from all curves | Remove `stepMode='left'` from **RX/Valve only**. TX curves **keep** `stepMode='left'`. |
| `plot_view.py` — `refresh()`       | Remove `stepMode` from all `setData()`   | Remove `stepMode` from **RX/Valve** `setData()` only. TX `setData()` **keeps** `stepMode='left'`. |
| `plot_view.py` — `_build_display_data()` | Apply hold+ramp to all curves      | Apply hold+ramp to **RX/Valve only**. TX returns data unchanged (step rendering handles it). |
| `plot_view.py` — constants         | `RAMP_FRAC = 0.25`                      | `RAMP_FRAC_RX = 1.0`                                 |
| `tests/test_v2_plot_view.py`       | Update stepMode test for all curves      | Verify TX retains `stepMode='left'`; verify RX/Valve have ramp points with `RAMP_FRAC_RX=1.0` |

### D5. Future Consideration

When supporting multiple customer profiles with different graph display
preferences, consider extracting `RAMP_FRAC_RX` into a `GraphDisplayConfig`
dataclass:

```python
@dataclass
class GraphDisplayConfig:
    ramp_frac_rx: float = 1.0      # RX/Valve diagonal fraction
    tx_step_mode: str = 'left'     # TX always step
    # future: ramp_frac_tx, color_scheme, etc.
```

**Current decision: NOT implementing this.** The project serves a single
customer. A hardcoded constant in `plot_view.py` is the correct level of
abstraction. Extracting a config dataclass now would be premature
generalization (YAGNI). This note exists solely to document the natural
extension point if requirements change.

### D6. Acceptance Criteria Delta

Rev.1 AC-02 and AC-03 are superseded:

| ID       | Rev.1                                             | Rev.2                                                        |
|----------|---------------------------------------------------|--------------------------------------------------------------|
| AC-02    | All transitions show diagonal ramp                | **TX**: vertical step (no ramp). **RX/Valve**: full diagonal |
| AC-03    | Hold >= 75% of sample period (`RAMP_FRAC<=0.25`) | **Removed.** `RAMP_FRAC_RX=1.0` means 0% hold, 100% ramp   |
| AC-02a   | --                                                | **New**: TX curves visually identical to ECR step behavior    |

All other acceptance criteria (AC-01, AC-04 through AC-07, PC-01 through PC-03)
remain unchanged.

---

| Review       | Signature | Date       |
|--------------|-----------|------------|
| Author (PL)  | --        | 2026-03-29 |
| Approval (PM)| --        | 2026-03-29 |
| Delta rev.2 Author (Architect) | -- | 2026-03-30 |
| Delta rev.2 Approval (PM)      | -- | 2026-03-30 |
