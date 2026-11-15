#!/usr/bin/env python3
"""F2P harness for the warp / mouse-ears check (DfAM tips 19/20).

A large flat first layer with sharp corners lifts at the corners (warping); the
fix is rounding the corners (R >= 3 mm) or mouse ears (disc 10 mm, 0.3 mm thick).
Positive: an 80x60x5 box trips warp_risk with a mouse_ears suggestion of 4 corners.
Negatives: a small footprint, a part standing on a narrow edge, and a rounded bed.

    python3 -I scripts/CAD/check-warp.py [socket]   # default /tmp/orca-cad-mcp.sock
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


def warp_notes(res):
    return [n for n in notes_of(res) if n.get("kind") == "warp_risk"]


def extras_of(res):
    """dfam_extras' return value is nested under `extras` in the analyze result."""
    if not isinstance(res, dict) or "__error__" in res:
        return {}
    e = res.get("extras")
    return e if isinstance(e, dict) else {}


def box(w, h, d, rotate=None):
    call("new_document")
    call("extrude_rect", width=w, height=h, distance=d)
    time.sleep(0.5)
    kw = {} if rotate is None else {"rotate": rotate}
    return safe_call("analyze_printability", body=0, **kw)


# --- (a) the canonical positive: an 80x60x5 box ------------------------------
res = box(80, 60, 5)
wn = warp_notes(res)
check(res.get("ok") is True, "analyze_printability runs on an 80x60x5 box")
check(len(wn) >= 1, "an 80x60x5 box yields a warp_risk note")

# --- (b) note placement: on the bed, down-facing, with tris ------------------
if wn:
    n0 = wn[0]
    at = n0.get("at"); nm = n0.get("normal"); tr = n0.get("tris")
    check(isinstance(at, list) and len(at) == 3 and abs(at[2]) < 0.01,
          "the warp_risk pin sits on the bed (z ~ 0): %s" % (at,))
    check(isinstance(nm, list) and len(nm) == 3 and abs(nm[0]) < 0.05 and abs(nm[1]) < 0.05 and nm[2] < -0.99,
          "the warp_risk normal points straight down ~[0,0,-1]: %s" % (nm,))
    check(isinstance(tr, list) and len(tr) > 0, "the warp_risk note carries tris[] triangle indices")
else:
    check(False, "the warp_risk pin sits on the bed (no warp_risk note)")

# --- (c) the mouse_ears suggestion lists the 4 sharp corners ------------------
sugs = res.get("suggestions", []) if isinstance(res, dict) else []
me = [s for s in sugs if s.get("kind") == "mouse_ears"]
check(len(me) >= 1, "suggestions include a mouse_ears entry")
if me:
    corns = me[0].get("corners")
    check(isinstance(corns, list) and len(corns) == 4, "mouse_ears lists the 4 sharp corners: %s" % (corns,))

# --- (d) the warnings mention mouse ears -------------------------------------
warn = res.get("warnings", []) if isinstance(res, dict) else []
check(any("mouse ears" in w for w in warn), "warnings mention mouse ears")

# --- (h) out["warp"] reflects the bed geometry ------------------------------
warp = extras_of(res).get("warp")
check(type(warp) is dict and "bed_mm" in warp and len(warp["bed_mm"]) == 2
      and abs(warp["bed_mm"][0] - 80) < 1 and abs(warp["bed_mm"][1] - 60) < 1,
      "extras.warp.bed_mm ~ [80, 60]: %s" % (warp,))

# --- (e) negative: small footprint ------------------------------------------
resE = box(30, 30, 5)
check(len(warp_notes(resE)) == 0, "a 30x30x5 box yields NO warp_risk note (footprint < 50 mm)")
check("warp" not in extras_of(resE), "a 30x30x5 box leaves extras.warp unset")

# --- (f) negative: standing on a narrow edge --------------------------------
resF = box(80, 60, 5, rotate=[90, 0, 0])
check(len(warp_notes(resF)) == 0,
      "the box standing on its 80x5 edge (rotate=[90,0,0]) yields NO warp_risk note (bed too small)")

# --- (g) negative: rounded bed corners --------------------------------------
call("new_document")
call("extrude_circle", diameter=80, distance=5)
time.sleep(0.5)
resG = safe_call("analyze_printability", body=0)
check(resG.get("ok") is True, "analyze_printability runs on a Ø80 circular plate")
check(len(warp_notes(resG)) == 0, "a Ø80 circular plate yields NO warp_risk note (rounded corners)")
check("warp" not in extras_of(resG), "a Ø80 circular plate leaves extras.warp unset")

print("CHECKS %d FAILED %d" % (_checks, len(fails)))
sys.exit(1 if fails else 0)
