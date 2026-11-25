# Review brief: Orca-CAD DfAM phase 3 (plan review, read-only)

You are reviewing a PLAN, not code. Nothing in the plan has been implemented. Read the code it points at and tell me where the plan is wrong.

## What to read

- `docs/CAD/dfam-study-2026-11.md` (this branch): the study. Section 1 = what exists, section 2 = items R1-R13, section 3 = order.
- Issue tracker: `bd show projects-8pdt.2` then `bd show projects-8pdt.2.<n>` for n = 1..13. Each has a description, an acceptance check and (R4, R6, R12, R13) a dependency.
- Code the plan builds on, all under `src/`:
  - `slic3r/GUI/CAD/McpControl.cpp`: `analyze_printability`, `dfam_extras` (~3620), `attach_print_fixes` (~4372), the `thin_wall` block (~4118), the edge/vertex classifier "tips 5/7/16" (~3812-3900), `tight_pair` (~4181), `text_indent` and `use_parameters` fixes.
  - `libslic3r/CAD/CadDocument.cpp`: `HoleStdEntry` table (~1226), `add_hole_styled`, thread groove (~3736), expression functions (~272).
  - `libslic3r/CAD/CadFeatureFields.hpp` (hole fields), `libslic3r/PrintConfig.cpp` (slicer settings named below).

## Measured facts (checked by grep/reading; do not re-theorise, but do verify against the files)

1. The code has no occurrence of `polyhole`, `elephant`, `stress.?relief`, `layer_height` under `libslic3r/CAD` and `slic3r/GUI/CAD`.
2. `analyze_printability` takes `line_width` (default 0.4), `clearance` (default 0.3), `overhang_angle` (45); there is no document-level nozzle / layer height / material.
3. `vertical_edge` fires only for `convex && |e.z| > 0.95`; the concave branch (`!convex`) requires `|e.z| < 0.1` and is the wall/floor junction (`base_corner`).
4. `thin_wall` computes `off_multiple_pct` and `thin_pct` but only emits a note when walls are under 2 line widths.
5. `tight_pair` stores one distance `d`; no per-axis decomposition.
6. Expression functions `abs sqrt ceil floor round max min` exist (`CadDocument.cpp:272-274`).
7. `PrintConfig.cpp` defines `elefant_foot_compensation`, `xy_hole_compensation`, `xy_contour_compensation`, `brim_ears`, `detect_thin_wall`, `min_feature_size`.
8. The printable bed shape is read from the config in `slic3r/GUI/CAD/DesignCanvas.cpp:787`.
9. The verb list has `fillet chamfer hole hole_styled hole_standard boolean pattern shell draft mirror split rib thicken delete_face helix` and no move/offset-face verb.

## My interpretations (challenge these)

- Items marked "already implemented" in study section 1 really are (teardrop, bridge strips, bottom fillet to chamfer, mouse ears, orientation).
- Baking elephant-foot and hole compensation into the model would double-compensate with the slicer, so they stay advice-first.
- R1 (document print profile) is the enabler for R4, R6, R12 and should come first; R2 (insert pockets) is the most valuable.
- Effort letters (S/M/L) and priorities are guesses, not measurements.

## Premises I could not verify (please settle each, with a source or a code citation)

- Heat-set insert pocket dimensions: study says the table must come from the maker's datasheet; I did not look any up.
- Stress-relief slots reduce warping: no source found; the plan keeps it advice-only.
- Whether `thin_wall` already catches thin glyph strokes of raised text (R4 assumes it does not).
- Whether adding document variables for R1 touches the 3MF/cereal recipe serialization in a way that breaks older files.
- Whether OCCT helical sweeps with a 45 deg flank profile (R10) are viable at all.
- Whether `apply_print_fix` can host a fix that edits more than one feature (R6, R9).

## What I want back

A markdown reply, findings ranked by severity, each with `file:line` evidence:

1. Any item in study section 1 wrongly classified as implemented, and any item in section 2 that is in fact already covered.
2. Wrong or missing code seams (a function or struct the plan names that does not exist or does something else).
3. Dependency or ordering mistakes among the 13 beads, and anything that should be split or merged.
4. Risks I did not list (serialization, undo, performance of mesh checks on large parts, false-positive rates, UX contract violations).
5. Anything in the acceptance checks that cannot fail (a vacuous test).

## Constraints

- Read-only: do not edit, build, commit or push. Do not run the app.
- Treat everything in the study as a claim to check, not as fact; the measured-fact list above is the only part I checked myself.
