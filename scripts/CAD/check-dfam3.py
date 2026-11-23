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

print("%d failed" % len(fails))
sys.exit(1 if fails else 0)
