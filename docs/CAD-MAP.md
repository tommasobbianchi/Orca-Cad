# CAD-MAP — the Design tab, as it actually is

Built 2026-09-04 by reading the source on `feature/cad-primitives`, not from the
existing docs. **Read this before changing anything under `src/libslic3r/CAD/` or
`src/slic3r/GUI/CAD/`.** Where a measurement later contradicts it, fix the map in the
same commit as the code — a stale map is worse than none, and this repository has
already proved that (see §6).

## 0. The one thing to hold in your head

A Design document is **a list of features and a bag of named variables. Everything
else is derived.** `recompute()` replays the list from nothing; bodies, meshes, the
compound `body`, per-triangle face/body ids are all outputs. That single fact explains
the rest of the design:

- **Undo is a snapshot of `features` + `variables`, nothing more** (`checkpoint()`,
  cap 200). It does not need to snapshot geometry, because geometry is a function of
  those two. One checkpoint == one Ctrl+Z.
- **Editing is transactional**: `remove_feature` / `move_feature` / `replace_feature`
  snapshot, mutate, `recompute()`, and roll back if the result is invalid — so a failed
  edit can never leave a broken body on screen.
- **Preview is the same replay with one extra feature appended**, into a scratch mesh
  (`preview()`), which is why the translucent ghost always agrees with what Confirm
  will produce.

## 1. Layout

| Where | What |
|---|---|
| `src/libslic3r/CAD/` | the kernel. No GUI dependency. ~10 kLOC. |
| `src/libslic3r/slvs/` | vendored SolveSpace constraint solver (LGPL), self-contained |
| `src/slic3r/GUI/CAD/` | the tab: `DesignPanel`, `DesignCanvas`, `DesignSketchTool`, `DesignOffer`, `SketchInlineEditor`, `McpControl` |
| `tests/libslic3r/test_*.cpp` | Catch2, ~9.7 kLOC, registered under `if (SLIC3R_CAD)` so they ride `libslic3r_tests`/`ctest` |
| `scripts/CAD/` | the dev harness — build, headless GUI, and the `check-*` rungs |

Kernel files: `CadDocument` (the feature tree and replay), `GeometryEngine` (OCCT
topology + tessellation + face/edge ids), `SketchEngine` / `SketchSolver` /
`SketchConstraints` / `SketchInference` / `SketchImport`, `ThreadStandards`.

## 2. The spine

`CadDocument::recompute()` — the sequencing function. Read it first and completely.

```
recompute()
  └── for each enabled feature:
        variables → eval_expr → assign_field   (parametric bindings, §4)
        route_feature(bodies, f)
              ├── datum types return immediately: Plane, Axis, CoordSys — no solid
              ├── Helix returns: it is a curve, consumed by Sweep
              ├── Project returns: sketch-like, consumed downstream
              ├── body-level ops dispatch to their own apply_*:
              │     Boolean, Cut, Mirror, Transform, Mate,
              │     Thicken, ThickenSurface, SurfaceOffset
              └── everything else → apply_feature(result, have_body, context, f)
                    a switch over CadFeatureType, throwing on failure
        → bodies[] → display_mesh + display_tri_face + display_tri_body
```

`apply_feature`'s `context` is subtle and worth the sentence the source gives it: it is
the body whose **faces and edges the feature reads** (face-extrude source, up-to-face
target, dress-up, hole), and it differs from `result` only when a feature builds a NEW
body out of an existing one.

## 3. Routes — there are two, and they are not interchangeable

**Route K (kernel).** `CadDocument` + OCCT only. Deterministic, headless, testable in
about two minutes. Every feature's geometry lives here.

**Route G (GUI).** `DesignPanel` (the form/feature-tree side), `DesignSketchTool` (the
sketch gesture machine — by far the largest file in the feature), `DesignCanvas`,
`GLGizmoSketch` (in-canvas drag gizmos), `DesignOffer` (the right-click offer that is
now the primary route to every verb; the toolbar is chrome). Route G needs a live
OpenGL canvas, a display, and a window manager.

A third, narrower route exists: **Route M (MCP)** — `McpControl.cpp` exposes the
kernel over JSON-RPC, which is how an agent drives the tab without a display.

**Which route your change takes decides which harness can prove it.** Kernel geometry
→ `run-kernel-tests.sh`, and CI can run it. Anything in Route G → the `check-gui-*.py`
rungs, which hosted CI cannot run at all.

## 4. Variables and expressions — the parametric layer

`CadDocument::variables` is `name -> expression`, evaluated topologically on each
recompute (a variable may reference another). A feature carries `expr`: a map from
*field member name* to expression string; on recompute each entry is evaluated and
written into the named numeric field (`eval_expr` at CadDocument.cpp:191,
`assign_field` at :3608).

Two consequences that are easy to get wrong:

- The undo snapshot **must** carry `variables` as well as `features`. The source says
  why, and it is not hypothetical: set a bad variable, watch recompute() fail, press
  undo, and without variables in the snapshot the bad variable survives, so every later
  recompute fails too.
- A field bound to an expression is overwritten on every recompute. Writing the numeric
  field directly and expecting it to stick is a bug that will not show until the next
  recompute.

## 5. What is verified, and what only exists

All 32 `CadFeatureType` values are implemented and routed. Nothing is a stub.

Coverage is a different question. Counting `CadFeatureType::X` mentions in
`tests/libslic3r/test_caddocument.cpp` (8291 lines):

| Feature | mentions |
|---|---|
| Sketch, Extrude | 24, 20 |
| Cut | 7 |
| Plane, Mate | 4 |
| Mirror | 3 |
| Hole, Revolve, Helix, Transform, Rib | 2 |
| Fillet, Chamfer, Thread, Shell, Sweep, Pattern, Loft, Draft, Boolean, Axis, CoordSys, Thicken, Project | 1 |
| **Import, DeleteFace** | **0** |
| **SurfaceExtrude, SurfaceRevolve, ThickenSurface, SurfaceOffset, SurfaceLoft, SurfaceFill** | **0** |

**The entire surface-modelling subsystem — six feature types — has no kernel test.**
It is the newest and least-verified area, and it is the one where OCCT is least
forgiving (offsets and thickenings fail on geometry that booleans handle fine). Same
for `Import` and `DeleteFace`, the two direct-editing entry points for imported STEP.

That is the honest state: breadth is done, verification did not keep up.

## 6. A correction this map already had to make

The first pass of the table above had an `apply_feature` column, and it read `NO` for
Plane, Cut, Mirror, Axis, CoordSys, Transform, Thicken, ThickenSurface, SurfaceOffset
and Mate — ten types that looked unimplemented. They are all implemented; they are
dispatched in `route_feature` to dedicated `apply_*` functions before `apply_feature`
is ever reached, and the datum types deliberately produce no solid at all.

A grep for the switch was measuring the wrong thing. **Confirm the stage runs before
calling it missing** — the same lesson the mesh2step port learned the expensive way.

## 7. The harness, and the two traps that cost a session each

| Command | Proves | Needs |
|---|---|---|
| `scripts/CAD/run-kernel-tests.sh` | kernel builds, `[CadDocument]` passes. **Exit 0 is the contract.** | Docker |
| `scripts/CAD/run-all-checks.sh` | everything below; the gate before pushing | Docker + GUI container |
| `check-sketch-engine.py` / `-corpus.py` | 2D loop count, closure, void attribution | kernel |
| `check-gui-sketching.py` | the same profiles drawn as a person draws them | headless GUI |
| `check-gui-context-menu.py` | right-click is the pivot of the gesture | headless GUI |
| `check-mcp-sketch.py` | the sketch layer over MCP | headless GUI + `SNAPORCA_MCP` |

- **Never build inside the GUI container.** Its baked source tree reconfigures the
  shared build directory and this fork's targets vanish.
- **A window manager is required.** Without one nothing gets focus, and an unfocused
  GTK app ignores synthetic keys — which reads exactly like a code bug.

`docs/rig_build_traps.md` has these and three more with recovery commands. Read it
before debugging any configure or link failure from these scripts.

## 8. Documents that are now wrong

`docs/GAP_ANALYSIS_vs_ONSHAPE.md` (2026-07-22) is superseded on its central claims. It
lists as absent: variables/expressions, surface modelling, mirror body, helix, datum
axis, coordinate system, thicken, project edges, delete face, rib, assemblies/mates.
**Every one of those now exists.** Its Tier-3 scope judgements still hold; its ranked
recommendation does not. Do not plan from it without checking the enum first.
