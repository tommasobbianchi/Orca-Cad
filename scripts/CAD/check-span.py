#!/usr/bin/env python3
"""F2P harness for the exact bridge span (inscribed-circle diameter of a flat roof).

A pocket cut from the bed face prints its ceiling as a downward-facing flat roof. Its
span used to be the bounding-box short side, which over-reports L / frame / ring shapes.
This checks the new inscribed-circle span: a rectangle reports its short side, an L
reports its narrowest corridor (~15), a disc reports its own diameter.

    python3 -I scripts/CAD/check-span.py [socket]   # default /tmp/orca-cad-mcp.sock
Exit 0 = every assertion held; exit 1 when any check failed.
"""
import json, socket, sys, time

SOCK = sys.argv[1] if len(sys.argv) > 1 else "/tmp/orca-cad-mcp.sock"
_n = 0


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


fails = []
_checks = 0


def check(cond, msg):
    global _checks
    _checks += 1
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def safe_call(method, **params):
    try:
        return call(method, **params)
    except Exception as e:  # noqa: BLE001 - a refused/missing verb is a FAIL, not a crash
        return {"__error__": str(e)}


def notes_of(res):
    if not isinstance(res, dict) or "__error__" in res:
        return []
    return res.get("notes", []) if isinstance(res.get("notes"), list) else []


def new_shell():
    """100x100x20 box on the bed (z 0..20): body 0."""
    call("new_document")
    call("extrude_rect", width=100, height=100, distance=20)
    time.sleep(0.4)


def pocket_rect(w, h, depth=8):
    """Cut a rectangular pocket open at z=0 (bed face), `depth` mm upward."""
    call("extrude_rect", width=w, height=h, distance=depth, boolean="subtract", body=0)
    time.sleep(0.4)


def pocket_circle(dia, depth=8):
    """Cut a circular pocket open at z=0, `depth` mm upward."""
    call("extrude_circle", diameter=dia, distance=depth, boolean="subtract", body=0)
    time.sleep(0.4)


def roof_levels(res):
    """`overhang_levels` entries (flat downward roofs), biggest area first."""
    if not isinstance(res, dict) or "__error__" in res:
        return []
    lv = res.get("overhang_levels")
    return lv if isinstance(lv, list) else []


# --- (a) a 60x40 rectangular pocket -> the ceiling spans ~40 (the short side) -----
new_shell()
pocket_rect(60, 40)
res = safe_call("analyze_printability", body=0)
lv = roof_levels(res)
check(res.get("ok") is True, "analyze_printability runs on a shell with a 60x40 pocket")
check(len(lv) >= 1, "the pocket ceiling shows up as an overhang level (got %d)" % len(lv))
if lv:
    L = lv[0]
    check(abs(L.get("z", 0) - 8.0) < 1.5, "the pocket is open at the bed face (ceiling z=%s ~8)" % L.get("z"))
    check(abs(L.get("span_mm", -1) - 40.0) < 1.5,
          "60x40 pocket ceiling spans ~40 (its short side), got %s" % L.get("span_mm"))

# --- (b) an L-shaped pocket = 60x15 overlapping 15x60 -> narrowest corridor ~15 ----
new_shell()
pocket_rect(60, 15)
pocket_rect(15, 60)
res = safe_call("analyze_printability", body=0)
lv = roof_levels(res)
check(res.get("ok") is True, "analyze_printability runs on a plus-shaped pocket")
if lv:
    span = lv[0].get("span_mm", -1)
    # two centred 60x15 pockets make a plus: the widest inscribed circle sits in the middle, 2*7.5*sqrt(2) = 21.2
    check(abs(span - 21.21) <= 1.5, "the plus-shaped pocket ceiling spans its inscribed circle (~21.2), got %s" % span)
    check(span < 30.0, "the plus span is below the old bounding-box value (was 60)")
    check(lv[0].get("too_long_to_bridge") == (span > 20.0), "too_long_to_bridge follows the inscribed span against the 20 mm limit")
else:
    check(False, "the L pocket ceiling appears as an overhang level")

# --- (c) a Ø30 circular pocket -> the ceiling spans its own diameter ----------------
new_shell()
pocket_circle(30)
res = safe_call("analyze_printability", body=0)
lv = roof_levels(res)
check(res.get("ok") is True, "analyze_printability runs on a Ø30 circular pocket")
if lv:
    check(abs(lv[0].get("span_mm", -1) - 30.0) < 1.5,
          "the Ø30 pocket ceiling spans ~30, got %s" % lv[0].get("span_mm"))

# --- (d) too_long_to_bridge flips for a wide roof, with a long_bridge note ---------
new_shell()
pocket_rect(60, 60)
res = safe_call("analyze_printability", body=0)
lv = roof_levels(res)
check(res.get("ok") is True, "analyze_printability runs on a 60x60 pocket")
if lv:
    check(lv[0].get("span_mm", -1) > 20.0, "the 60x60 pocket span is over 20, got %s" % lv[0].get("span_mm"))
    check(lv[0].get("too_long_to_bridge") is True, "a 60x60 pocket is too long to bridge")
check(any(n.get("kind") == "long_bridge" for n in notes_of(res)),
      "a long_bridge note exists for the 60x60 roof")

# --- (e) a small overhang (4 mm) is marked; a 15 mm one is not "small" -----------------
new_shell()
pocket_rect(4, 4)
res = safe_call("analyze_printability", body=0)
sm = [n for n in notes_of(res) if n.get("kind") == "small_overhang"]
check(len(sm) == 1, "a 4x4 pocket roof gets one small_overhang note (got %d)" % len(sm))
check(bool(sm) and sm[0].get("tris") and sm[0].get("normal") is not None, "the small_overhang note has tris and a normal")
new_shell()
pocket_rect(15, 15)
res = safe_call("analyze_printability", body=0)
check(not any(n.get("kind") == "small_overhang" for n in notes_of(res)), "a 15x15 pocket roof is not a small_overhang")

print("CHECKS %d FAILED %d" % (_checks, len(fails)))
sys.exit(1 if fails else 0)
