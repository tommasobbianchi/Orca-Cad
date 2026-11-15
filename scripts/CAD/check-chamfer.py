#!/usr/bin/env python3
"""F2P harness for the steep-chamfer check (DfAM tips 9/10).

A chamfer on a bed-facing edge must be 45 deg; a shallower one is an overhang
that needs support. The `chamfer` verb only makes equal 45 deg chamfers, so the negatives (45 deg bottom
chamfer, top-edge chamfer, 30 deg flare) use it, and the positive is a 60 deg flared wall
made with extrude_rect taper=60 (a planar face 60 deg from vertical overhangs).

    python3 -I scripts/CAD/check-chamfer.py [socket]   # default /tmp/orca-cad-mcp.sock
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


def steep_notes(res):
    return [n for n in notes_of(res) if n.get("kind") == "steep_chamfer"]


def extras_of(res):
    if not isinstance(res, dict) or "__error__" in res:
        return {}
    e = res.get("extras")
    return e if isinstance(e, dict) else {}


def box_chamfer(w, h, d, edge_z, dist):
    call("new_document")
    call("extrude_rect", width=w, height=h, distance=d)
    time.sleep(0.5)
    cf = safe_call("chamfer", where={"kind": "line", "z": edge_z}, distance=dist, body=0)
    time.sleep(0.3)
    res = safe_call("analyze_printability", body=0)
    return res, cf


# --- (a) 45 deg chamfer on the four bottom edges: negative --------------------
res, cf = box_chamfer(40, 40, 20, 0.0, 5.0)
check(cf.get("ok") is True and "chamfer_index" in cf,
      "chamfer on the four bottom edges (z=0) succeeds: %s" % (cf,))
check(res.get("ok") is True, "analyze_printability runs after the 45 deg chamfer")
check(len(steep_notes(res)) == 0,
      "a 45 deg chamfer yields NO steep_chamfer note (45 deg is at the overhang limit)")
warn = res.get("warnings", []) if isinstance(res, dict) else []
check(not any("Sloped face" in w for w in warn),
      "a 45 deg chamfer adds no sloped-face warning")
sc = extras_of(res).get("shallow_chamfers")
check(sc is None or (isinstance(sc, list) and len(sc) == 0),
      "a 45 deg chamfer leaves shallow_chamfers empty (was %s)" % (sc,))

# --- (b) 45 deg chamfer on the TOP edges: negative (faces up) ----------------
res2, cf2 = box_chamfer(40, 40, 20, 20.0, 5.0)
check(cf2.get("ok") is True and "chamfer_index" in cf2,
      "chamfer on the four top edges (z=20) succeeds: %s" % (cf2,))
check(len(steep_notes(res2)) == 0,
      "a chamfer on the TOP edges faces up: NO steep_chamfer note")

# --- (c) plumbing: the z=0 line filter matches exactly the 4 bottom edges -----
call("new_document")
call("extrude_rect", width=40, height=40, distance=20)
time.sleep(0.5)
sel = safe_call("select_topology", type="edge", where={"kind": "line", "z": 0}, body=0)
check(sel.get("count") == 4,
      "where {kind:line, z:0} matches exactly the 4 bottom edges (count=%s)" % (sel.get("count"),))

# --- (d) positives: a flared (tapered) wall is a planar overhang -------------
# taper = flare of the side wall from vertical; face is 60 deg from vertical -> overhang.
call("new_document")
call("extrude_rect", width=20, height=20, distance=5, taper=60)
time.sleep(0.5)
res = call("analyze_printability", body=0)
sn = [n for n in res.get("notes", []) if n.get("kind") == "steep_chamfer"]
check(len(sn) >= 1 and sn[0].get("severity") == "warning", "60 deg flared wall yields a steep_chamfer warning note")
check(bool(sn) and sn[0].get("normal") and sn[0]["normal"][2] < 0 and bool(sn[0].get("tris")), "steep_chamfer note has a downward normal and tris")
sc = (res.get("extras") or {}).get("shallow_chamfers", res.get("shallow_chamfers")) or []
check(len(sc) >= 1 and abs(sc[0].get("from_vertical_deg", 0) - 60.0) < 1.0, "shallow_chamfers reports ~60 deg from vertical (%s)" % (sc[:1],))
check(any(x.get("kind") == "steep_chamfer" for x in res.get("suggestions", [])), "a steep_chamfer suggestion is listed")
call("new_document")
call("extrude_rect", width=20, height=20, distance=5, taper=30)
time.sleep(0.5)
res = call("analyze_printability", body=0)
check(not any(n.get("kind") == "steep_chamfer" for n in res.get("notes", [])), "30 deg flare prints unsupported: NO steep_chamfer note")

print("CHECKS %d FAILED %d" % (_checks, len(fails)))
sys.exit(1 if fails else 0)
