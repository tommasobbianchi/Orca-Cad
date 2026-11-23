# DfAM list vs Orca-CAD: what exists, what is left, how to build it

Written 2026-11-23 from reading `src/slic3r/GUI/CAD/McpControl.cpp` (`analyze_printability`, `dfam_extras`, `attach_print_fixes`),
`src/libslic3r/CAD/CadDocument.cpp` and `PrintConfig.cpp`. Nothing here was run: statements about the code are from reading it;
effort numbers and priorities are estimates (DEDOTTO), not measurements.

## 0. The two mechanisms the code already has

- **A. Analysis note + `apply_print_fix`.** `analyze_printability` works on the print-oriented mesh, emits numbered notes
  (`wall`, `warp_risk`, `long_bridge`, ...), `attach_print_fixes` maps a note kind to a parametric edit (sets a flag on an existing
  feature, or adds a small feature). Non-destructive, undoable, shows as pins in the viewport. Cheapest way to add a rule.
- **B. A parametric feature or option** (hole teardrop, bridge strips, text, thread...). Needed when the geometry must be part of the design.

Inputs the checks get today: `line_width` (default 0.4), `clearance` (default 0.3), `overhang_angle` (45), `layer_h` (hole only).
There is **no document-level print profile** (nozzle, layer height, material). Bed shape is reachable (`DesignCanvas.cpp:787`).

## 1. Filter: already implemented (not studied further)

| List item | Where it lives |
|---|---|
| 1 Teardrop horizontal holes | `hole_teardrop`, `hole_teardrop_flat` (flat top snapped up to a layer), note `horizontal_hole` + fix |
| 1 Sequential bridging under a counterbore | `hole_bridge_layer_h` (two crossed sacrificial strips), notes `sacrificial_layer`, `long_bridge` |
| 1 Bottom fillet to chamfer | note `fillet_from_below` + fix (suppress the fillet, chamfer the bed edges at its radius) |
| 5 Mouse ears | note `warp_risk`, suggestion `mouse_ears` (disc 10 mm, 0.3 mm thick) + fix |
| 3/5 Print orientation | note `orientation` (six axis-aligned ways up ranked by overhang area) + fix; `curve_axis` |
| 4 Thin walls (detection only) | note `thin_wall` (< 2 line widths) |
| 2 Tight pairs (detection only) | note `tight_pair`, one isotropic clearance |

Partly done (the remainder is in section 2): 1 gussets (ribs under a long roof exist, no gusset/chamfer under a shelf),
1 compound base profile, 3 XY corner fillets (convex vertical edges only), 4 wall multiples (measured, not reported), 4 Z multiples
(only for hole strips), 6 text (raised to cut conversion exists, no bed-face or wall rules).

## 2. What is left, one by one

Format: **gap** / design / code seam / risk / effort / check.

### R1. Document-level print profile (enabler for most items below)
- **Gap:** nozzle, line width, layer height, material live nowhere in the document; each verb takes its own number.
- **Design:** four document variables (`nozzle`, `line_w`, `layer_h`, `material`) with defaults, saved with the design; `analyze_printability`
  reads them when a param is missing; the Print check panel shows them. Variables already exist and expressions have `ceil floor round min max`
  (`CadDocument.cpp:272`), so every later rule can be a bound expression.
- **Risk:** low. **Effort:** S. **Check:** change `layer_h`, the teardrop flat and bridge strips follow without touching the hole.

### R2. Heat-set insert pockets and captive-nut traps (list 3) - highest practical value
- **Gap:** only the text advice `slit_nut_trap`; `HoleStdEntry` (`CadDocument.cpp:1226`) has clearance / counterbore / countersink only.
- **Design:** new hole style `insert` driven by a table (M2..M5: pocket diameter, depth, lead-in chamfer, melt chamber below) and a
  `nut_trap` feature (hexagon at across-flats + clearance, cut from the side, closed by a `hole_bridge_layer_h` strip). Detection note:
  thread or tapped hole smaller than M6 in plastic suggests an insert. Table values must come from the insert maker's datasheet, not from me.
- **Seam:** `add_hole_styled`, `hole_standard` verb, schema in `McpControl.cpp` ~351. **Risk:** low-medium (values, not code). **Effort:** M.
- **Check:** pocket diameter equals the table value in `query_topology`; print a test coupon.

### R3. Per-axis clearance (list 2)
- **Gap:** `tight_pair` takes the nearest distance `d` and one threshold (0.3), no direction.
- **Design:** decompose the min-distance vector: XY gap vs Z gap, thresholds `clear_xy` (~0.2) and `clear_z` (~0.25 or a layer multiple).
  Note says which axis is short. Fix needs an "offset/move face" operation that does not exist in the verb list: ship detection first.
- **Risk:** low for detection; fix blocked. **Effort:** S (detect), L (fix). **Check:** two boxes 0.1 mm apart in X, then in Z: note names the right axis.

### R4. Text rules (list 6)
- **Gap:** only `text_indent` (raised becomes cut). No stroke check, no distinction bed face / vertical wall.
- **Design:** (a) minimum stroke: offset the glyph polygons inward by `line_w` (Clipper is in libslic3r); area lost means the stroke is
  thinner than 2 line widths, report the character; fix = bolden or enlarge. (b) face-aware: on the bed face engrave 1-2 layers (`n * layer_h`);
  on vertical walls clamp a raised depth to 0.4-0.8 and give the extrude a 45 deg bottom taper (taper exists on extrude).
- **Seam:** `text_indent` fix in `attach_print_fixes`, text sketch wires. **Risk:** medium (glyph compounds can be multi-contour). **Effort:** M.
- **Check:** text 3 mm high in a thin font: note appears; a bold font: no note.

### R5. Knife edges (list 4)
- **Gap:** nothing detects acute convex tips or edges.
- **Design:** reuse the edge adjacency of tips 5/7 (`McpControl.cpp` ~3812): convex edge with dihedral wedge under ~30 deg, then ray inward along
  the bisector, report if the thickness at 1 line width from the tip is under ~1.2-1.5 x nozzle. Fix: a chamfer cannot raise thickness; the right edit
  is a flat truncation (cut by a plane) or a larger angle, so start with detection and a suggested minimum tip width.
- **Risk:** medium (false positives on fillet seams). **Effort:** M. **Check:** a 15 deg wedge fires, a 60 deg wedge does not.

### R6. Wall multiples and Z multiples (list 4)
- **Wall:** `thin_wall` already computes `off_multiple_pct` but emits no note. Add a note giving the nearest multiples of `line_w`
  (e.g. 0.84, 1.26, 1.68 for 0.4 mm) and, only when the wall maps to one parametric feature (thin extrude, shell, thicken), a fix that rounds that parameter.
  When two features could own the wall, skip the fix (same rule `steep_chamfer` uses). The slicer's own `detect_thin_wall` and gap fill already
  soften this, so keep it a suggestion.
- **Z:** with R1, bind critical heights (membrane, bridge strip, step) to `ceil(x / layer_h) * layer_h`. The slicer snaps any height to its layers anyway,
  so the gain is for thin features only; limit it to those.
- **Risk:** low. **Effort:** M (wall), S (Z). **Check:** wall of 0.9 mm, line 0.4: note names 0.84 and 1.26.

### R7. Gussets and shelf undersides (list 1)
- **Gap:** `long_bridge` fix adds ribs across a roof span; nothing chamfers or braces a shelf that overhangs a wall.
- **Design:** if the overhang depth is small, chamfer the shelf-underside/wall edge so the face is at least 45 deg (chamfer verb, edge from topology);
  if deeper, a triangular gusset (`rib` verb, 45 deg profile). Choose by overhang depth vs allowed chamfer.
- **Risk:** low-medium. **Effort:** S (chamfer path), M (gusset). **Check:** an L-bracket shelf, note fires, fix leaves overhang area at 0 in `analyze_printability`.

### R8. Concave vertical corners and stress risers (list 3)
- **Gap:** `vertical_edge` is convex only (`convex && |e.z| > 0.95`); the concave branch is the wall/floor junction (`base_corner`, edge not vertical).
- **Design:** add a concave vertical branch (`!convex && |e.z| > 0.95`), same note family, fillet fix reuses the existing one.
- **Risk:** low. **Effort:** S. **Check:** a pocket with square inner corners fires.

### R9. Elephant foot and vertical-hole compensation (list 2) - overlap with the slicer
- **Fact:** OrcaSlicer already has `elefant_foot_compensation`, `xy_hole_compensation` and `xy_contour_compensation` (`PrintConfig.cpp`). Baking the same
  correction into the model double-compensates and makes the nominal dimension untrue, which breaks mates and fit checks.
- **Design:** do not bake. (a) Note when a bed-contact edge has no chamfer and the slicer value is 0: suggest the slicer setting first, an optional
  0.2-0.4 mm chamfer (the `fillet_from_below` chamfer path) second. (b) Holes: a "print allowance" variable the user binds (`d + hole_comp`),
  one-click through the `use_parameters` pattern; polygon (polyhole) style only on request.
- **Risk:** low if kept optional. **Effort:** S. **Check:** note disappears once the chamfer or the slicer value exists.

### R10. Printed-thread profile (list 3)
- **Gap:** threads are ISO profile (`ThreadStandards.cpp`; helical groove at `CadDocument.cpp` ~3736).
- **Design:** option `profile=print`: 45 deg flanks, flat crest of about P/4, clearance on internal threads. Helical sweeps in OCCT are the fragile part.
- **Risk:** high. **Effort:** M-L. **Priority:** low until large printed threads are a real use case.

### R11. Vertical pegs and anisotropy (list 3)
- **Gap:** orientation ranks by overhang only; nothing looks at slender features loaded across layers.
- **Design:** detect slender bosses (length / diameter above a threshold) whose axis is Z (the `curve_axis` smooth-component grouping gives axes);
  advice only: rotate (the orientation fix exists), or a D-flat for printing on its side. Load direction is unknown to the CAD, so no automatic fix.
- **Risk:** medium (false alarms). **Effort:** S-M.

### R12. Stress-relief slots (list 5)
- **Gap:** none. **Design:** for a bed-contact face longer than ~150 mm and an ABS/ASA/PC `material` (R1), suggest slots
  (1 mm wide, partial depth). I have not verified the benefit from a source; treat it as a hypothesis and keep it advice only.
- **Effort:** S (advice), M (cut feature). **Priority:** low.

### R13. Auto-split with joints (list 5)
- **Gap:** `split` verb exists (manual plane). No choice of plane, no dowels, dovetails or magnet seats.
- **Design:** step 1 detect "does not fit the bed" (bed shape is available, `DesignCanvas.cpp:787`); step 2 propose a plane minimizing overhang
  and cross-section; step 3 add dowel pins and matching clearance holes with R3 clearances. Each step is its own feature.
- **Risk:** high (booleans on two bodies, clearances). **Effort:** L. **Priority:** low-medium; step 1 alone is cheap (S) and useful.

## 3. Suggested order (estimates)

1. R1 print profile (S) - unlocks the rest.
2. R2 inserts and nut traps (M) - most useful for real parts.
3. R4 text rules (M), R5 knife edges (M), R8 concave corners (S), R3 per-axis clearance detection (S).
4. R6, R7, R9, R11 (S-M each).
5. R10, R12, R13 (L or low value).

## 4. Rules for every new check

- One falsification script per check in `scripts/CAD/check-*.py` (the existing `check-printnotes.py` shows the shape): a part that must fire and a near miss that must not.
- No correction is baked into the model if the slicer already has the setting; advice first, fix second.
- UI strings in English; follow the Design UX contract (parameters only on cards, ribbon Confirm/Cancel).
