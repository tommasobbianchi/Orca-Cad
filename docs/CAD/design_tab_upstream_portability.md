# Design (CAD) tab — integration surface

What the Design tab adds to OrcaSlicer, what it touches that upstream already has, and the
constraints that come with it. The dependency cost is measured separately in
[cad_dependency_weight.md](cad_dependency_weight.md); this page does not repeat its numbers.

## Two gates

- **Compile time: `SLIC3R_CAD`** (`CMakeLists.txt`, default ON in this tree). OFF builds no
  CAD code at all and leaves the OCCT deps prefix identical to upstream. ON also turns on
  OCCT's `ModelingAlgorithms` module (`deps/OCCT/OCCT.cmake`).
- **Run time: Preferences → CAD feature (experimental)** (`enable_cad_feature`, default OFF).
  Off, the Design page and the MCP control socket are not created, the Prepare-toolbar Sketch
  and Primitive gizmos cannot be selected, and the Design-only preferences are hidden: Prepare
  behaves as it does without the feature. A project that carries a CAD recipe still loads,
  keeps the recipe and writes it back unchanged.

## Dependencies

OCCT is already an upstream dependency (STEP import, SVG, text shapes). The Design tab adds no
library; it widens the OCCT build by one module, which builds three extra toolkits — TKFillet,
TKOffset and TKFeat — of which the first two are linked. The module flag is all-or-nothing, so
TKFeat is built although nothing references it.

The constraint solver is vendored in `src/libslic3r/slvs/`: a self-contained subset of
SolveSpace (`libslvs`), GPL-3.0, no external dependencies. GPLv3 §13 and AGPLv3 §13 permit the
combination with OrcaSlicer's AGPL-3.0.

## Footprint in upstream files

Almost all of the change is new files under `src/libslic3r/CAD/`, `src/slic3r/GUI/CAD/`,
`src/libslic3r/slvs/` and `tests/`. The hooks into existing code are small and null-guarded:

- `GLCanvas3D` — a `DesignSketchTool` pointer plus render, mouse and key hooks, each a no-op
  when no Design canvas owns it.
- `MainFrame` — the Design page and the Edit menu routing Undo/Redo to it while it is shown.
- `Plater` — the "no geometry" warning distinguishes a recipe-only project.
- `Model` — one `std::string cad_recipe`, empty for non-CAD projects.
- `bbs_3mf` — reading and writing that string (below).
- `Preferences`, `GUI_App` — the two preferences.

Nothing in the slicing pipeline (Print, PrintObject, Layer, GCode), Tab, or the profile and
config system changes.

## The 3MF entry

```
Metadata/orca_cad.bin      written only when cad_recipe is non-empty
Metadata/SnapOrca_cad.bin  legacy name: read, never written; loses to orca_cad.bin
```

Readers that do not know the entry ignore it and writers skip it when the recipe is empty, so
projects without a design are byte-identical and older readers are unaffected. The reader caps
the entry at 1 GiB.

The entry is a cereal `PortableBinaryArchive`, portable across endianness and word size. Its
layout is versioned:

- **v5 and later** frame every feature separately, so fields are appended to
  `CadFeature::serialize` without a version bump and an older reader skips what it does not
  know. Optional document-level data (variables, body names, origin, colours, the
  auto-close setting) follows in trailing blocks that a reader stops at cleanly when absent.
- **v4** is the flat layout, read by the frozen `CadFeature::load_flat_v4`, which must never
  change.

Checked-in fixtures `tests/data/cad_recipe_v3.bin`, `cad_recipe_v4.bin` and
`cad_recipe_v5.bin` hold the format still: `test_caddocument.cpp` loads them and checks what
they contain, so a reordered field fails the suite instead of breaking saved projects.

`Import` features embed OCCT's ASCII BRep of the imported solid, which ties a saved project to
a BRep revision OCCT can read.

## Undo

The Design tab keeps its own history (`CadDocument` checkpoints), separate from the Plater's
snapshot stack. The Edit menu's Undo/Redo drive whichever of the two belongs to the page on
screen.
