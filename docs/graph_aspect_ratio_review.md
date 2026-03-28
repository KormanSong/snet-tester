# Graph Aspect Ratio Review

## Topic
- Should the main trend graph remain wide as it is now, or move closer to the square-like graph ratio used in the legacy calibration program?

## Current State
- Main window default size: `1280 x 820`
- Central layout split: left/right = `5 : 2`
- Measured current ratio plot size at default window:
  - `ratio plot = 791 x 386`
  - aspect ratio is approximately `2.05 : 1`
- Current valve plot is separated below the main plot at fixed height:
  - `valve plot = 791 x 120`

## Legacy Context
- Existing in-house calibration program is closer to `4:3`
- Operators are likely familiar with a graph that feels nearly square
- Graph controls such as time-axis change or axis mode change lived below the graph

## Team Summary

### UI Designer View
- A near-square graph is easier to read and more familiar to existing operators
- A very wide graph gives better time-axis spread, but can feel thin and unfamiliar
- Best balance is a `quasi-square` main graph, not a perfectly square graph and not the current stretched shape

### Architect View
- Current wide graph works well with the left-monitor / right-work layout
- But it should not become so shallow that multi-channel traces lose vertical readability
- Best compromise is:
  - keep left graph + right work area
  - keep wide-shell layout
  - make the main graph taller
  - add a control strip below the graph

### Critic View
- Users familiar with square-ish graphs may misread the same data when the graph becomes much wider
- Wide graphs improve time reading but can weaken small vertical-change recognition
- Safer default is to stay closer to the old familiar ratio at first

## Comparison

### 1. Near-Square Graph
#### Advantages
- Strong operator familiarity
- More stable perception of up/down change
- Better fit for multi-channel reading when traces are dense
- Natural place for a bottom control strip

#### Disadvantages
- Less time-axis spread in one view
- Slow transients and long comparisons may feel compressed
- Can make the overall modern window feel cramped if taken too far

### 2. Current Wide Graph
#### Advantages
- Better for long time-axis observation
- Better for delay, phase, and sequence comparison
- Fits current left-graph / right-control layout naturally
- Leaves room for graph options, legends, and annotations

#### Disadvantages
- Feels less familiar to operators used to the legacy program
- Can reduce vertical readability of small variations
- May look wide and efficient, but still pressure the lower control area if graph controls are added

## PM Decision
- Do not force a return to a perfect square graph
- Do not keep the current graph as a very wide strip either
- Recommended direction: `quasi-square main graph`

## Recommended Target Direction
- Main ratio graph should move toward a visual ratio around:
  - `1.5 : 1` to `1.8 : 1`
- This keeps:
  - familiarity from the legacy calibration tool
  - enough horizontal room for time trends
  - enough vertical room for multi-channel readability
  - a natural bottom strip for graph controls

## Recommended Layout Shape
- Left side remains graph-dominant
- Right side remains work/control area
- Inside the left graph zone:
  - top: status strip
  - center: main ratio graph with taller body
  - bottom: graph control strip
  - optional lower area: separated valve graph or summary

## Practical Development Guidance

### P0
- Increase main ratio graph height from the current default behavior
- Reserve a fixed bottom strip for graph controls:
  - time window
  - axis mode
  - scale mode
  - selection helpers

### P1
- Avoid hard-wiring the graph into an overly wide ratio at all window sizes
- Add resize rules so graph height does not collapse too aggressively

### P2
- Consider separate layout presets:
  - `Operator View`
  - `Review / Report View`

## Safer Default
- For initial release or transition, use a ratio closer to the legacy feel
- In practice, this means a taller main graph rather than the current wide shape

## PM Recommendation To Boss
- Keep the overall `left graph / right work area` structure
- Move the main graph toward a `quasi-square` feel
- Add the graph control strip below it
- Treat this as the safest transition path for operators already trained on the legacy calibration program
