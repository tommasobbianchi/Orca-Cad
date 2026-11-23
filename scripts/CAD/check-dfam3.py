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

print("%d failed" % len(fails))
sys.exit(1 if fails else 0)
