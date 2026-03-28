# SNET Protocol Tester Graph Design Report

## Goal
- Define a graph design strategy that clearly separates the monitoring area from the rest of the industrial UI.
- Provide a practical recommendation for the current bright-gray control screen and a fallback policy for an XP-gray style UI.

## PM Summary
- Boss direction is valid and should be adopted as a design rule, not treated as a cosmetic preference.
- The graph must look like a dedicated measurement surface, not like another settings panel.
- For the current bright-gray application tone, the best fit is a `black scope graph`.
- If the overall application tone later moves toward a Win XP style gray, the correct fallback is a `white paper graph`.

## Inputs
- Current code uses a single `PlotTheme` inside [`plot_view.py`](C:/Users/xcvoi/work/snet-tester/src/snet_tester/views/plot_view.py).
- Current graph area is visually close to the rest of the panel background.
- Boss requirement:
  - Graph and non-graph areas must be clearly separated.
  - If the app is XP-gray, graph should be white with black supporting lines.
  - If the app is bright-gray, graph should be black with scope-like visibility.

## Team Findings

### UI Designer
- The graph should feel like a separate instrument.
- For bright-gray UI, black scope style gives the strongest hierarchy and fastest visual pickup.
- For XP-gray UI, white background with black guides gives better document-like readability.

### Architect
- Current `PlotTheme` structure is too flat for theme branching.
- Theme data and rendering logic should be separated.
- Recommended theme strategy:
  - `Auto`
  - `White`
  - `Scope Black`

### Critic
- Current graph and surrounding UI are too close in tone.
- Long-session readability suffers when graph and shell share similar brightness.
- Channel color and state color must not be mixed.

## Design Decision

### Final Recommendation
- Use `Scope Black` as the primary graph theme for the current application.

### Why
- The existing product direction is a bright-gray industrial control UI.
- A black graph creates an immediate hierarchy break between `monitoring` and `control`.
- It reduces ambiguity about where the operator should look for dynamic behavior.
- It better supports long monitoring sessions when line contrast is controlled properly.

### Secondary Policy
- If the full application shell is intentionally redesigned toward a classic XP-gray tone, switch the graph to `White Paper`.

## Theme Comparison

### Option A: White Paper
- Best when the shell is darker gray or XP-like.
- Graph background: pure white or near white
- Axes: black or deep gray
- Grid: thin neutral gray
- Main line: black or charcoal
- Support lines: restrained colors only
- Best qualities:
  - print-friendly
  - remote-support friendly
  - familiar engineering worksheet feel
- Risks:
  - weaker separation if the shell itself is also very bright
  - less dramatic focus pull than black scope

### Option B: Scope Black
- Best when the shell is bright gray and the graph must act as a dedicated monitoring surface.
- Graph background: near black
- Axes: light gray
- Grid: very dark gray, thin
- Main traces: cyan, green, yellow with strict limits
- Alarm and threshold lines: reserved, fixed semantic colors
- Best qualities:
  - strongest separation from the shell
  - fast visual pickup
  - operator attention stays on the live signal area
- Risks:
  - can become noisy if too many bright colors are used
  - requires disciplined state-color policy

## Required Design Rules

### 1. Separation
- The graph panel border, background, and brightness must be intentionally different from the shell.
- The graph should read as a measurement area, not as another form.

### 2. Color Policy
- Channel colors and state colors must be separate systems.
- Example:
  - Channel colors: cyan, lime, yellow, magenta
  - State colors: green for live, amber for stale, red for alarm

### 3. Grid Policy
- Grid must support reading, not decoration.
- Major grid lines may be slightly stronger than minor lines.
- Grid density should remain readable in screenshots and remote desktop.

### 4. Axis Policy
- Axis labels must remain readable after screenshot compression.
- Critical labels should not depend on ultra-thin lines or low-contrast text.

### 5. Selection Policy
- Selected channel should be dominant.
- Non-selected channels should be visibly subordinate.
- This is more important than showing all channels equally brightly.

### 6. Threshold Policy
- Target line, alarm threshold, and stale indication must have fixed meanings.
- They must never reuse ordinary channel colors.

## Concrete Visual Specification

### Scope Black
- Panel background: `#1A1D21`
- Plot background: `#000000`
- Major grid: `#2B3138`
- Minor grid: `#181C21`
- Axis line: `#AEB8C2`
- Axis text: `#D8DEE6`
- Selected trace: `#39FF14` or `#00E5FF`
- Non-selected traces: lower alpha or muted variants
- Setpoint line: `#FFD400`
- Alarm threshold: `#FF5A4F`
- Stale line style: dashed amber

### White Paper
- Panel background: `#C9CED4` to `#D7DBE0`
- Plot background: `#FFFFFF`
- Major grid: `#AAB2BA`
- Minor grid: `#D3D8DE`
- Axis line: `#1C1F23`
- Axis text: `#111111`
- Selected trace: `#111111`
- Support traces: muted blue, muted green, muted red only where needed
- Setpoint line: `#3A3F45`
- Alarm threshold: `#B42318`
- Stale line style: dashed dark gray

## Recommended Product Rule
- `If shell tone is bright gray -> graph theme = Scope Black`
- `If shell tone is XP gray or darker neutral gray -> graph theme = White Paper`

## Implementation Notes
- Replace the current single theme object with theme spec data.
- Add graph theme modes:
  - `auto`
  - `white`
  - `scope_black`
- Keep `ratio` and `valve` under the same family but give the valve plot lower emphasis.
- Do not introduce gradients, glow, glossy effects, or decorative chrome.

## Output Artifacts
- Comparison image: [`graph_theme_comparison.png`](C:/Users/xcvoi/work/snet-tester/artifacts/graph_theme_comparison.png)
- Preview generator: [`graph_theme_preview.py`](C:/Users/xcvoi/work/snet-tester/src/snet_tester/graph_theme_preview.py)

## PM Recommendation To Boss
- Approve `Scope Black` as the default graph direction for this product.
- Keep `White Paper` as a supported fallback theme policy, not as the primary current direction.
- If you want, next step is to convert this report into:
  - a `graph-specific Screen Spec`, or
  - an actual refactor of [`plot_view.py`](C:/Users/xcvoi/work/snet-tester/src/snet_tester/views/plot_view.py)
