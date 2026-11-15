#!/usr/bin/env python3
"""F2P harness for the mesh-integrity check (DfAM tip 21).

A closed, consistently wound mesh slices; gaps (open edges) and reversed faces make
the slicer fail or print holes. The check runs inside analyse_printability and emits
a `mesh_integrity` warning note only when a problem exists, so the positives here are
mesh defects injected as STL files (one triangle omitted / one triangle's winding
reversed), and the negatives are the clean primitives.

    python3 -I scripts/CAD/check-meshfix.py [socket]   # default /tmp/orca-cad-mcp.sock
Exit 0 = every assertion held; exit 1 when any check failed.
"""
import json, os, socket, sys, time

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


def extras_of(res):
    if not isinstance(res, dict) or "__error__" in res:
        return {}
    e = res.get("extras")
    return e if isinstance(e, dict) else {}


def mi_notes(res):
    return [n for n in notes_of(res) if n.get("kind") == "mesh_integrity"]


# --- a unit-style 10 mm cube as ASCII STL; omit/reverse one triangle ----------
VOL = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
       (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
TRIS = [
    (0, 2, 1), (0, 3, 2),   # bottom, -z
    (4, 5, 6), (4, 6, 7),   # top, +z
    (0, 1, 5), (0, 5, 4),   # front, y=0
    (3, 7, 6), (3, 6, 2),   # back, y=10
    (0, 4, 7), (0, 7, 3),   # left, x=0
    (1, 2, 6), (1, 6, 5),   # right, x=10
]


def write_cube_stl(path, omit=None, reverse=None):
    tri = list(TRIS)
    if reverse is not None:
        t = list(tri[reverse]); t[1], t[2] = t[2], t[1]; tri[reverse] = tuple(t)
    with open(path, "w") as f:
        f.write("solid cube\n")
        for idx, t in enumerate(tri):
            if idx == omit:
                continue
            p0, p1, p2 = (VOL[i] for i in t)
            u = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
            w = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
            nx = u[1] * w[2] - u[2] * w[1]
            ny = u[2] * w[0] - u[0] * w[2]
            nz = u[0] * w[1] - u[1] * w[0]
            f.write("  facet normal %g %g %g\n" % (nx, ny, nz))
            f.write("    outer loop\n")
            for p in (p0, p1, p2):
                f.write("      vertex %g %g %g\n" % p)
            f.write("    endloop\n  endfacet\n")
        f.write("endsolid cube\n")


os.makedirs("/tmp/claude-1000", exist_ok=True)

# --- (a) a clean box: no mesh_integrity note, no result key -------------------
call("new_document")
call("extrude_rect", width=40, height=40, distance=20)
time.sleep(0.5)
res = safe_call("analyze_printability", body=0)
check(res.get("ok") is True, "analyze_printability runs on a clean box")
check(len(mi_notes(res)) == 0, "a clean box yields NO mesh_integrity note")
check("mesh_integrity" not in extras_of(res), "a clean box result has no mesh_integrity key")

# --- (b) a box with a drilled bore: still watertight --------------------------
call("new_document")
call("extrude_rect", width=40, height=40, distance=20)
time.sleep(0.3)
hole = safe_call("hole", diameter=8, through=True, plane="XY", x=0, y=0)
time.sleep(0.3)
res = safe_call("analyze_printability", body=0)
check(hole.get("ok") is True, "the hole verb succeeds on the box")
check(res.get("ok") is True, "analyze_printability runs on the box with a bore")
check(len(mi_notes(res)) == 0, "a drilled bore is watertight: NO mesh_integrity note")
check("mesh_integrity" not in extras_of(res), "the bore-box result has no mesh_integrity key")

# --- (c) a cube missing one triangle: an open gap ------------------------------
call("new_document")
gap_path = "/tmp/claude-1000/open-cube.stl"
write_cube_stl(gap_path, omit=4)   # omit the first top triangle
r = safe_call("import_mesh", path=gap_path)
check(r.get("ok") is True and r.get("bodies", 0) >= 1,
      "import_mesh reads the gapped STL (%s)" % (r,))
time.sleep(0.3)
res = safe_call("analyze_printability", body=0)
mi = mi_notes(res)
check(bool(mi) and mi[0].get("severity") == "warning",
      "the gapped cube yields a mesh_integrity warning note")
extra = extras_of(res).get("mesh_integrity") or {}
check(extra.get("open_edges", 0) >= 3,
      "the gapped cube reports open_edges >= 3 (%s)" % (extra.get("open_edges"),))
warns = res.get("warnings", []) if isinstance(res, dict) else []
check(any("gaps" in w for w in warns), "warnings text mentions gaps")
check(any(s.get("kind") == "mesh_repair" for s in res.get("suggestions", [])),
      "a mesh_repair suggestion is listed")

# --- (d) a cube with one triangle's winding reversed ---------------------------
call("new_document")
rev_path = "/tmp/claude-1000/reversed-cube.stl"
write_cube_stl(rev_path, reverse=4)   # flip the first top triangle
r = safe_call("import_mesh", path=rev_path)
check(r.get("ok") is True and r.get("bodies", 0) >= 1,
      "import_mesh reads the reversed-face STL (%s)" % (r,))
time.sleep(0.3)
res = safe_call("analyze_printability", body=0)
# import_mesh sews the triangles into a B-rep and the display mesh is re-tessellated from it,
# so a flipped triangle is repaired on import: the body is watertight and nothing is flagged.
check(r.get("watertight") is True, "import_mesh repairs the reversed triangle (watertight)")
check(not any(n.get("kind") == "mesh_integrity" for n in notes_of(res)),
      "the repaired reversed-face cube yields NO mesh_integrity note")

print("CHECKS %d FAILED %d" % (_checks, len(fails)))
sys.exit(1 if fails else 0)
