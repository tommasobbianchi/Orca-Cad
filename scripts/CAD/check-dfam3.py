#!/usr/bin/env python3
"""F2P harness for DfAM phase 3 (beads projects-8pdt.2): R1 print profile, R2 insert pocket,
R3 per-axis clearance, R8 inside vertical corners. Each rule has a must-fire case AND a near-miss.

    python3 -I scripts/CAD/check-dfam3.py [socket]   # default /tmp/orca-cad-mcp.sock
Exit 0 = every assertion held.
"""
import json, socket, sys, time

SOCK = sys.argv[1] if len(sys.argv) > 1 else "/tmp/orca-cad-mcp.sock"
_n = 0
fails = []


def call(method, **params):
    global _n
    _n += 1
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(90)
    s.connect(SOCK)
    s.sendall((json.dumps({"jsonrpc": "2.0", "id": _n, "method": method, "params": params}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        d = s.recv(65536)
        if not d:
            break
        buf += d
    s.close()
    r = json.loads(buf.decode())
    if "error" in r:
        raise RuntimeError("%s: %s" % (method, r["error"]))
    return r["result"]


def safe(method, **params):
    try:
        return call(method, **params)
    except Exception as e:  # noqa: BLE001
        return {"__error__": str(e)}


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def kind_notes(res, kind):
    ns = res.get("notes", []) if isinstance(res, dict) else []
    return [n for n in ns if isinstance(n, dict) and n.get("kind") == kind]


def fresh():
    call("new_document")
    time.sleep(0.4)


def box(w, h, d):
    call("extrude_rect", width=w, height=h, distance=d)
    time.sleep(0.4)


def pair(dx, dz):
    fresh()
    box(20, 20, 10)
    box(20, 20, 10)
    safe("transform", body=1, dx=dx, dz=dz)
    time.sleep(0.4)
    return safe("analyze_printability", body=0)


# --- R8: inside vertical corners ---
fresh()
box(100, 100, 20)
box(60, 40, 8)
safe("transform", body=1, dz=12)
safe("boolean", op="subtract", target=0, tool=1)
time.sleep(0.4)
res = safe("analyze_printability", body=0)
check(len(kind_notes(res, "inside_vertical_edge")) > 0, "R8: a pocket with square inner corners fires inside_vertical_edge")
fresh()
box(40, 40, 20)
res = safe("analyze_printability", body=0)
check(len(kind_notes(res, "inside_vertical_edge")) == 0, "R8 near-miss: a plain box has no inside vertical corner")

# --- R3: per-axis clearance (defaults: xy 0.2, z 0.25) ---
n = kind_notes(pair(20.1, 0), "tight_pair")
check(len(n) == 1 and n[0].get("axis") == "xy", "R3: 0.1 mm apart in X -> tight_pair naming xy (%s)" % [x.get("axis") for x in n])
n = kind_notes(pair(0, 10.1), "tight_pair")
check(len(n) == 1 and n[0].get("axis") == "z", "R3: 0.1 mm apart in Z -> tight_pair naming z (%s)" % [x.get("axis") for x in n])
check(len(kind_notes(pair(20.3, 0), "tight_pair")) == 0, "R3 near-miss: 0.3 mm apart in X -> no note")
check(len(kind_notes(pair(20.22, 0), "tight_pair")) == 0, "R3 near-miss: 0.22 mm in X clears the 0.2 xy limit -> no note")
check(len(kind_notes(pair(0, 10.22), "tight_pair")) == 1, "R3: 0.22 mm in Z is under the 0.25 z limit -> note")

# --- R2: heat-set insert pocket ---
fresh()
box(30, 30, 15)
v0 = safe("mass_properties", body=0).get("volume")
r = safe("hole_standard", designation="M3 insert", x=0, y=0, plane="XY")
check(r.get("ok") is True, "R2: hole_standard 'M3 insert' runs (%s)" % (r.get("__error__") or "ok"))
v1 = safe("mass_properties", body=0).get("volume")
check(isinstance(v0, (int, float)) and isinstance(v1, (int, float)) and abs((v0 - v1) - 3.14159265 * 2.0 * 2.0 * 6.0) < 3.0,
      "R2: pocket removes pi*2^2*6 = 75.4 mm3 (got %s)" % (None if v0 is None or v1 is None else round(v0 - v1, 1)))
r = safe("hole_standard", designation="M7 insert", x=5, y=5, plane="XY")
check("__error__" in r or r.get("ok") is False, "R2 near-miss: unknown insert size is refused")

# --- R1: print profile ---
fresh()
box(30, 30, 15)
safe("set_variable", name="print_layer_h", expr="0.3")
r = safe("hole", diameter=6, depth=8, x=0, y=0, plane="XY", teardrop=True, teardrop_flat=1.0)
check(r.get("ok") is True, "R1: a teardrop hole is made (%s)" % (r.get("__error__") or "ok"))
lf = safe("list_fields", feature=r.get("hole_index", 2))
check("print_layer_h" in json.dumps(lf), "R1: the hole's layer height is bound to print_layer_h")
res = safe("analyze_printability", body=0)
check("__error__" not in res, "R1: analyze_printability runs with a print profile")

# --- Print check after undo / redo (reported 2026-11-23: undo did not bring the notes back) ---
def n_pins():
    ins = safe("ui.inspect")
    pn = ins.get("print_notes") if isinstance(ins, dict) else None
    return len(pn) if isinstance(pn, list) else -1


fresh()
box(100, 100, 20)
box(60, 40, 8)
safe("transform", body=1, dz=12)
safe("boolean", op="subtract", target=0, tool=1)
time.sleep(0.6)
n0 = n_pins()
check(n0 > 0, "undo: the pocket part shows Print check notes after the edits (%d)" % n0)
safe("apply_print_fix", kind="inside_vertical_edge", body=0)
time.sleep(0.6)
safe("undo")
time.sleep(0.6)
n2 = n_pins()
check(n2 == n0, "undo: one undo of the fix brings the notes back (%d, was %d)" % (n2, n0))
safe("redo")
time.sleep(0.6)
safe("undo")
time.sleep(0.6)
check(n_pins() == n0, "undo: redo then undo again shows the same notes (%d, was %d)" % (n_pins(), n0))
safe("undo")
time.sleep(0.6)
n3 = n_pins()
check(n3 >= 0, "undo: a second undo (removes the boolean) keeps a valid Print check (%d notes)" % n3)

# --- R4a: strokes thinner than the nozzle line ---
def text_note(h):
    fresh()
    box(60, 30, 5)
    safe("add_text", text="Orca 8", height=h, plane="XY", body=0, extrude_distance=0.6, boolean="union")
    time.sleep(0.5)
    return kind_notes(safe("analyze_printability", body=0), "thin_text")


n = text_note(1.2)
print("probe 1.2 mm:", [x.get("lost_pct") for x in n])
check(len(n) == 1, "R4: 1.2 mm text (strokes under the 0.4 mm line) fires thin_text")
n = text_note(8)
print("probe 8 mm:", [x.get("lost_pct") for x in n])
check(len(n) == 0, "R4 near-miss: 8 mm text has strokes wider than the line -> no note")

# --- R4b: face-aware text_indent fix ---
fresh()
box(40, 40, 20)
r = safe("add_text", text="ORCA", height=8, plane="XZ", body=0, extrude_distance=1.5, boolean="union")
idx = max(0, int(safe("list_commands").get("feature_count", 0)) - 1) if False else None
safe("analyze_printability", body=0)
fx = safe("apply_print_fix", kind="text_indent", body=0)
check(fx.get("ok") is not False and "__error__" not in fx, "R4b: apply_print_fix text_indent runs (%s)" % (fx.get("__error__") or "ok"))
dist = [json.dumps(safe("list_fields", feature=i)) for i in range(1, 6)]
import re
vals = [float(m) for d in dist for m in re.findall(r'"distance"[^0-9-]*([0-9.]+)', d)]
print("distances:", vals)
check(any(0.39 <= v <= 0.81 for v in vals), "R4b: wall text depth clamped to 0.4-0.8 mm after the fix")


# --- R5: knife edge ---
import math


def wedge(deg):
    fresh()
    h = 30 * math.tan(math.radians(deg / 2))
    safe("sketch_begin", plane="XY")
    safe("sketch_add", entities=[{"type": "line", "p0": [0, 0], "p1": [30, h]}, {"type": "line", "p0": [30, h], "p1": [30, -h]},
                                 {"type": "line", "p0": [30, -h], "p1": [0, 0]}], infer=False)
    sk = safe("sketch_commit")
    safe("extrude", sketch=sk.get("sketch_index", 0), distance=10)
    time.sleep(0.5)
    return safe("analyze_printability", body=0)


check(len(kind_notes(wedge(15), "knife_edge")) == 1, "R5: a 15 deg wedge fires knife_edge")
check(len(kind_notes(wedge(60), "knife_edge")) == 0, "R5 near-miss: a 60 deg wedge does not")
fresh()
box(30, 30, 20)
safe("fillet", radius=3, edges=[0])
check(len(kind_notes(safe("analyze_printability", body=0), "knife_edge")) == 0, "R5 near-miss: a filleted box edge (smooth seam) does not")

# --- R6 / R7 / R9 / R11 / R12 / R13 step 1 ---
def cup(inner):   # open box with 4 walls of (20 - inner) / 2 mm
    fresh()
    safe("set_variable", name="print_multiples", expr="1")   # the multiples checks are opt-in
    box(20, 20, 10)
    box(inner, inner, 10)
    safe("transform", body=1, dz=2)
    safe("boolean", op="subtract", target=0, tool=1)
    time.sleep(0.4)
    return kind_notes(safe("analyze_printability", body=0, line_width=0.42), "wall_multiple")


check(len(cup(18.2)) >= 1, "R6: 0.9 mm walls with a 0.42 line get a wall_multiple note")
check(len(cup(18.32)) == 0, "R6 near-miss: 0.84 mm walls (2 lines) get none")

fresh()
box(40, 40, 20)
safe("primitive", shape="box", at=[30, 0, 10], width=20, depth=40, height=3, boolean="union", body=0)
check(len(kind_notes(safe("analyze_printability", body=0), "shelf_underside")) >= 1, "R7: a shelf joined to a wall above the bed fires shelf_underside")
fresh()
box(40, 40, 20)
check(len(kind_notes(safe("analyze_printability", body=0), "shelf_underside")) == 0, "R7 near-miss: a plain box has no shelf underside")

fresh()
box(30, 30, 10)
check(len(kind_notes(safe("analyze_printability", body=0), "elephant_foot")) == 1, "R9: a box on the bed fires elephant_foot")
safe("set_variable", name="print_elefant_comp", expr="0.2")
check(len(kind_notes(safe("analyze_printability", body=0), "elephant_foot")) == 0, "R9 near-miss: print_elefant_comp > 0 silences it")

fresh()
safe("primitive", shape="cylinder", radius=2.5, height=30)
check(len(kind_notes(safe("analyze_printability", body=0), "slender_peg")) == 1, "R11: a 5 x 30 mm vertical peg fires slender_peg")
fresh()
safe("primitive", shape="cylinder", radius=10, height=10)
check(len(kind_notes(safe("analyze_printability", body=0), "slender_peg")) == 0, "R11 near-miss: a 20 x 10 mm boss does not")

fresh()
box(200, 50, 5)
safe("set_variable", name="print_warp_prone", expr="1")
check(len(kind_notes(safe("analyze_printability", body=0), "stress_relief_slots")) == 1, "R12: a 200 mm base on a warp-prone material fires")
fresh()
box(100, 50, 5)
safe("set_variable", name="print_warp_prone", expr="1")
check(len(kind_notes(safe("analyze_printability", body=0), "stress_relief_slots")) == 0, "R12 near-miss: 100 mm base does not")
fresh()
box(200, 50, 5)
check(len(kind_notes(safe("analyze_printability", body=0), "stress_relief_slots")) == 0, "R12 near-miss: PLA (flag unset) does not")

fresh()
box(300, 50, 5)
check(len(kind_notes(safe("analyze_printability", body=0), "exceeds_bed")) == 1, "R13.1: a 300 mm part does not fit the default bed")
fresh()
box(200, 50, 5)
check(len(kind_notes(safe("analyze_printability", body=0), "exceeds_bed")) == 0, "R13.1 near-miss: a 200 mm part fits")

# --- R13 step 2: one split plane that keeps both halves in the bed ---
fresh()
box(300, 50, 5)
res = safe("analyze_printability", body=0)
nn = kind_notes(res, "exceeds_bed")
fx = (nn[0].get("fix") if nn else None) or {}
check(bool(fx.get("steps")) and fx["steps"][0].get("method") == "cut", "R13.2: an oversize part gets a cut fix (%s)" % (fx.get("label") or nn))
r = safe("apply_print_fix", kind="exceeds_bed", body=0)
time.sleep(0.5)
check("__error__" not in r, "R13.2: apply_print_fix exceeds_bed runs (%s)" % (r.get("__error__") or "ok"))
bodies = [safe("analyze_printability", body=i) for i in (0, 1)]
fits = all("__error__" not in b and max(b.get("footprint_mm", [999, 999])) <= 256 for b in bodies)
check(fits, "R13.2: both halves are inside the 256 mm bed (%s)" % [b.get("footprint_mm") for b in bodies])
fresh()
box(600, 50, 5)
nn = kind_notes(safe("analyze_printability", body=0), "exceeds_bed")
check(len(nn) == 1 and not (nn[0].get("fix") or {}).get("steps"), "R13.2 near-miss: a part needing two cuts gets no single-cut fix")

# --- R13 step 3: dowels with sockets ---
import math as _m
fresh()
box(60, 40, 20)
safe("set_variable", name="print_bed_x", expr="45")
safe("set_variable", name="print_bed_y", expr="45")   # both ways round, or the part just turns to fit
res = safe("analyze_printability", body=0)
nn = kind_notes(res, "exceeds_bed")
dw = (nn[0].get("dowels") if nn else None) or {}
check(dw.get("count") == 2 and abs(dw.get("diameter_mm", 0) - 5.0) < 1e-6, "R13.3: a 60 x 40 x 20 cut face gets 2 dowels of d5 (%s)" % dw)
r = safe("apply_print_fix", kind="exceeds_bed", body=0)
time.sleep(0.8)
check("__error__" not in r, "R13.3: the dowel fix runs (%s)" % (r.get("__error__") or "ok"))
vols = [safe("mass_properties", body=i).get("volume") for i in range(4)]
print("R13.3 volumes:", vols)
want_half = 30 * 40 * 20 - 2 * _m.pi * 2.7 ** 2 * 10
want_rod = _m.pi * 2.5 ** 2 * (20 - 0.5)
check(all(isinstance(v, (int, float)) for v in vols) and abs(vols[0] - want_half) < 2 and abs(vols[1] - want_half) < 2,
      "R13.3: each half has two 5.4 mm sockets 10 mm deep (%.1f, %.1f, want %.1f)" % (vols[0] or -1, vols[1] or -1, want_half))
check(isinstance(vols[2], (int, float)) and abs(vols[2] - want_rod) < 2 and isinstance(vols[3], (int, float)),
      "R13.3: two rods d5 x 19.5 mm exist (%s, want %.1f)" % (vols[2:], want_rod))
fresh()
box(300, 50, 5)
nn = kind_notes(safe("analyze_printability", body=0), "exceeds_bed")
check(nn and "dowels" not in nn[0], "R13.3 near-miss: a 5 mm thick cut face (under 8 mm) gets no dowels")


# --- fixes for R9 / R7 ---
fresh()
box(30, 30, 10)
vol0 = safe("mass_properties", body=0).get("volume")
r = safe("apply_print_fix", kind="elephant_foot", body=0)
time.sleep(0.5)
check("__error__" not in r, "R9 fix: apply_print_fix elephant_foot runs (%s)" % (r.get("__error__") or "ok"))
vol1 = safe("mass_properties", body=0).get("volume")
check(vol0 - vol1 > 3 and vol0 - vol1 < 10, "R9 fix: 4 bed edges chamfered 0.3 mm remove ~5.4 mm3 in all (lost %.1f)" % (vol0 - vol1))

fresh()
box(40, 40, 20)
safe("primitive", shape="box", at=[30, 0, 10], width=20, depth=40, height=3, boolean="union", body=0)
vol0 = safe("mass_properties", body=0).get("volume")
r = safe("apply_print_fix", kind="shelf_underside", body=0)
time.sleep(0.5)
check("__error__" not in r, "R7 fix: apply_print_fix shelf_underside runs (%s)" % (r.get("__error__") or "ok"))
vol1 = safe("mass_properties", body=0).get("volume")
check(vol1 - vol0 > 20, "R7 fix: a 1.5 mm chamfer on the concave join ADDS material (gained %.1f mm3)" % (vol1 - vol0))


# --- R2 fix: thread -> insert ---
fresh()
box(30, 30, 15)
v0 = safe("mass_properties", body=0).get("volume")
safe("thread", radius=1.5, pitch=0.5, height=6, depth=0.3, internal=True, x=0, y=0, plane="XY")
time.sleep(0.5)
v_thread = safe("mass_properties", body=0).get("volume")
tn = kind_notes(safe("analyze_printability", body=0), "thread_insert")
check(len(tn) == 1 and (tn[0].get("fix") or {}).get("steps"), "R2 fix: an M3 internal thread gets a thread_insert note with a fix (%s)" % (len(tn)))
r = safe("apply_print_fix", kind="thread_insert", body=0)
time.sleep(0.5)
check("__error__" not in r, "R2 fix: apply_print_fix thread_insert runs (%s)" % (r.get("__error__") or "ok"))
v_ins = safe("mass_properties", body=0).get("volume")
check(abs((v0 - v_ins) - 75.4) < 3.0 and abs((v0 - v_thread) - (v0 - v_ins)) > 10,
      "R2 fix: the thread is replaced by the 75.4 mm3 insert pocket (thread removed %.1f, now %.1f)" % (v0 - v_thread, v0 - v_ins))
safe("undo"); time.sleep(0.3)
check(abs(safe("mass_properties", body=0).get("volume") - v_thread) < 1.0, "R2 fix: undo brings the thread back in one step")


# --- R2: nut trap ---
fresh()
box(30, 30, 15)
v0 = safe("mass_properties", body=0).get("volume")
r = safe("nut_trap", designation="M3", x=0, y=0, plane="XY")
check(r.get("ok") is True, "R2: nut_trap M3 runs (%s)" % (r.get("__error__") or r.get("error") or "ok"))
af = 5.5 + 0.4
hexa = af * af * math.sqrt(3) / 2   # area of a regular hexagon with flats af apart
v1 = safe("mass_properties", body=0).get("volume")
check(abs((v0 - v1) - hexa * (2.4 + 0.25)) < 2.0, "R2: M3 nut trap removes hexagon %.1f mm2 x 2.65 mm = %.1f mm3 (got %.1f)" % (hexa, hexa * 2.65, v0 - v1))
r = safe("nut_trap", designation="M3", x=0, y=8, plane="XY", slot=14)
v2 = safe("mass_properties", body=0).get("volume")
check(r.get("ok") is True and (v1 - v2) > hexa * 2.65, "R2: a slotted trap removes more than the plain hexagon (%.1f)" % (v1 - v2))
r = safe("nut_trap", designation="M7", x=0, y=0, plane="XY")
check("__error__" in r or r.get("ok") is False, "R2 near-miss: an unknown nut size is refused")


# --- R1: nozzle sets the default line width ---
def wall_lw():
    return (safe("analyze_printability", body=0).get("extras") or {}).get("walls", {}).get("line_width_mm")


fresh()
box(20, 20, 10)
check(abs((wall_lw() or 0) - 0.4) < 1e-6, "R1: no profile: line width 0.4 (%s)" % wall_lw())
safe("set_variable", name="print_nozzle", expr="0.6")
check(abs((wall_lw() or 0) - 0.63) < 1e-6, "R1: print_nozzle 0.6 gives line width 0.63 (%s)" % wall_lw())
safe("set_variable", name="print_line_w", expr="0.5")
check(abs((wall_lw() or 0) - 0.5) < 1e-6, "R1: an explicit print_line_w wins over the nozzle (%s)" % wall_lw())


# --- R2: inch sizes ---
fresh()
box(30, 30, 15)
v0 = safe("mass_properties", body=0).get("volume")
r = safe("nut_trap", designation="#6-32 UNC", x=0, y=0, plane="XY")
af = 7.938 + 0.4
v1 = safe("mass_properties", body=0).get("volume")
want = af * af * math.sqrt(3) / 2 * (2.778 + 0.25)
check(r.get("ok") is True and abs((v0 - v1) - want) < 3.0, "R2: #6-32 nut trap removes %.1f mm3 (got %.1f)" % (want, v0 - v1))
fresh()
box(30, 30, 15)
v0 = safe("mass_properties", body=0).get("volume")
r = safe("hole_standard", designation="#6-32 insert", x=0, y=0, plane="XY")
v1 = safe("mass_properties", body=0).get("volume")
want = math.pi * (4.22 / 2) ** 2 * 7.93
check(r.get("ok") is True and abs((v0 - v1) - want) < 3.0, "R2: '#6-32 insert' pocket removes %.1f mm3 (got %.1f)" % (want, v0 - v1))
r = safe("hole_standard", designation="1/4-20 insert", x=5, y=5, plane="XY")
check("__error__" in r or r.get("ok") is False, "R2 near-miss: 1/4-20 insert is refused (the sheet has no row)")


# --- R6 fix: wall and Z-height multiples ---
fresh()
call("extrude_rect", width=20, height=10, distance=0.9, plane="XZ")   # a 0.9 mm wall standing in Y
safe("set_variable", name="print_multiples", expr="1")
safe("set_variable", name="print_line_w", expr="0.42")   # the document's line width, which apply_print_fix re-reads
time.sleep(0.4)
res = safe("analyze_printability", body=0)
wn = kind_notes(res, "wall_multiple")
check(len(wn) == 1 and (wn[0].get("fix") or {}).get("steps"), "R6 fix: a 0.9 mm wall extrude gets a wall_multiple note with a fix (%s)" % len(wn))
v0 = safe("mass_properties", body=0).get("volume")
r = safe("apply_print_fix", kind="wall_multiple", body=0)
time.sleep(0.5)
v1 = safe("mass_properties", body=0).get("volume")
check("__error__" not in r and abs(v1 - 20 * 10 * 0.84) < 1.0, "R6 fix: the wall becomes 2 lines = 0.84 mm (volume %.1f, want 168)" % v1)

fresh()
box(20, 20, 10.07)
safe("set_variable", name="print_layer_h", expr="0.2")
check(len(kind_notes(safe("analyze_printability", body=0), "z_height_multiple")) == 0, "R6: off by default: no z_height_multiple without print_multiples")
safe("set_variable", name="print_multiples", expr="1")
zn = kind_notes(safe("analyze_printability", body=0), "z_height_multiple")
check(len(zn) == 1 and (zn[0].get("fix") or {}).get("steps"), "R6: a 10.07 mm part on 0.2 mm layers gets z_height_multiple with a fix (%s)" % len(zn))
r = safe("apply_print_fix", kind="z_height_multiple", body=0)
time.sleep(0.5)
v1 = safe("mass_properties", body=0).get("volume")
check("__error__" not in r and abs(v1 - 4000.0) < 1.0, "R6 fix: the height becomes 10.0 mm (volume %.1f, want 4000)" % v1)
fresh()
box(20, 20, 10.0)
safe("set_variable", name="print_layer_h", expr="0.2")
safe("set_variable", name="print_multiples", expr="1")
check(len(kind_notes(safe("analyze_printability", body=0), "z_height_multiple")) == 0, "R6 near-miss: 10.0 mm on 0.2 mm layers gets none")
fresh()
box(20, 20, 10.07)
safe("set_variable", name="print_multiples", expr="1")
check(len(kind_notes(safe("analyze_printability", body=0), "z_height_multiple")) == 0, "R6 near-miss: no layer height set, no judgement")

print("%d failed" % len(fails))
sys.exit(1 if fails else 0)
