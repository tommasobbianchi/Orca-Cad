# L3 Service — `l3_service`

A standalone, headless **JSON-RPC 2.0 over a Unix socket** front-end for the
Orca CAD kernel (`libslic3r`). Built for TaglIAtelle L3: it lets the
deterministic Python core drive the frozen-sketch kernel without the GUI or a
model provider.

## What it does

| Method | Action |
|---|---|
| `status` | service/protocol version, `ORCA_CAD_RECIPE_VERSION`, uptime, method list |
| `recipe.decode` | base64 cereal recipe blob → feature/variable summary |
| `recipe.apply` | deserialize a frozen recipe, project workpiece-contour edges as construction refs, add text features, recompute → recompute status + FNV-1a recipe digest |
| `sketch.boolean2d` | 2D boolean on polygon loops: `union|intersection|difference|xor` (ClipperUtils) |
| `sketch.text` | UTF-8 → mm glyph contour regions (stb_truetype via Emboss, bundled HarmonyOS font) |

Deterministic and serial: one client at a time, no randomness, no wall-clock in
method outputs (`uptime_seconds` is metadata only).

## Build

```bash
# kernel + service, in the same Docker env as the kernel-suite contract (OOM-guarded)
./scripts/CAD/build-l3-service.sh
# → build/src/L3Service/Release/l3_service
```

The verification contract is the kernel suite (`scripts/CAD/run-kernel-tests.sh`,
exit 0 = build + [CadDocument]/[Sketch*]/[slvs] tags pass). This service adds a
separate `l3_service` target; it does not alter kernel sources.

## Run & smoke test

```bash
./build/src/L3Service/Release/l3_service --socket /tmp/l3.sock --resources <repo>/resources
# --resources is required for sketch.text (bundled font lives under resources/fonts/).
# Defaults: $SNAPORCA_L3_SOCK or /tmp/snaporca-l3.sock; $SNAPORCA_RESOURCES or <cwd>/resources.

printf '{"jsonrpc":"2.0","id":1,"method":"status"}\n' | nc -U /tmp/l3.sock
```

## Notes

- **NanoSVG**: `nsvgParse*`/`nsvgDelete` are supplied by `nanosvg_impl.cpp`
  (a single `NANOSVG_IMPLEMENTATION` TU) — `libslic3r.a` does not contain them;
  the GUI/tests provide their own `#define`.
- **Static-archive ordering**: `CMakeLists.txt` wraps the archive set in
  `-Wl,--start-group/--end-group`, and `l3_service.cpp` carries a volatile
  `LocalesUtils` anchor for the `admesh → CNumericLocalesSetter` reverse dep
  (see the comment there).
- Edge ids for `project_edges_into_sketch` are session-scoped and unstable across
  `recompute()` — resolve and feed them in the same run.
