#!/usr/bin/env python3
"""F2P harness for the dfam print-check pins, phase 2 (beads projects-5y3p / 7omh / b11y / qnir / uiv8).

Covers spec postconditions 1-5. The checks for features that do not exist yet (red tint,
side list, hidden-pin normals, global notes, bore-roof walls) are EXPECTED to FAIL against the
current binary; the two negative cases (a 8 mm bore gives no thin_wall note; a part with no
notes leaves the side list empty) must pass.

    python3 -I scripts/CAD/check-printnotes.py [socket]   # default /tmp/orca-cad-mcp.sock
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


def thin_walls(res):
    return [n for n in notes_of(res) if n.get("kind") == "thin_wall"]


def box_with_bore(dia):
    """60x40x20 box centred on the bed, a through horizontal bore (axis along Y) centred at z=10."""
    call("new_document")
    call("extrude_rect", width=60, height=40, distance=20)
    call("hole", diameter=dia, through=True, plane="XZ", x=0, y=10)
    time.sleep(0.5)
    return safe_call("analyze_printability", body=0)


# --- Postcondition 4 (5y3p): bore-roof walls -----------------------------------------------
res = box_with_bore(19.4)
tw = thin_walls(res)

check(res.get("ok") is True, "analyze_printability runs on a 60x40x20 box with a through Ø19.4 horizontal bore")
check(len(tw) >= 1, "a Ø19.4 horizontal bore under a 20 mm lid yields a thin_wall note (bore-roof wall)")
if tw:
    at = tw[0].get("at")
    org = call("describe_scene")["modeling_origin"]   # notes are in the model frame; the bore's roof line runs along y at x = origin x, z = 19.7
    ok = isinstance(at, list) and len(at) == 3 and abs(at[0] - org[0]) < 1 and abs(at[2] - 19.7) < 1
    check(ok, "the thin_wall note sits on the bore roof line (x within 1 mm of the origin x, z within 1 mm of 19.7): %s, origin %s" % (at, org))
else:
    check(False, "the thin_wall note sits on the bore roof line (no thin_wall note)")
warn = res.get("warnings", []) if isinstance(res, dict) else []
check(any(("thinnest" in w or "walls thinner" in w) for w in warn),
      "warnings report walls thinner than 2 line widths with thinnest ~0.3 mm")

# --- Postcondition 1 (7omh): red tint data ------------------------------------------------
SURF = {"long_bridge", "sacrificial_layer", "fillet_from_below", "thin_wall"}
surf_notes = [n for n in notes_of(res) if n.get("kind") in SURF]
check(all(isinstance(n.get("tris"), list) for n in surf_notes),
      "surface notes carry tris[] triangle indices (capped at 2000) for the red tint")

ins = safe_call("ui.inspect")
pn = ins.get("print_notes") if isinstance(ins, dict) else None
check(isinstance(pn, list) and len(pn) >= 1,
      "ui.inspect reports a non-empty print_notes list (open/tinted_tris state)")
check(isinstance(pn, list) and all(isinstance(p.get("n"), int) and isinstance(p.get("open"), bool)
                                   and isinstance(p.get("tinted_tris"), int) for p in pn),
      "each print_notes entry carries n, open and tinted_tris")

# --- Postcondition 3 (qnir): hidden-pin normals -------------------------------------------
check(all(isinstance(n.get("normal"), list) and len(n.get("normal")) == 3 for n in notes_of(res) if n.get("at") is not None),   # pin-less global notes have no normal
      "every note carries a normal [x, y, z] for hidden-pin culling")

# --- Postcondition 2 (b11y): side list ----------------------------------------------------
# select the top face so the print_check verb applies (btn: verb needs a matching selection)
org = call("describe_scene")["modeling_origin"]
top = call("ui.worldToScreen", point=[org[0], org[1], 20.0])
call("ui.click", at=[top["x"], top["y"]])
time.sleep(0.4)
try:
    call("run_verb", verb="print_check")
    rv_ok = True
except RuntimeError as e:
    rv_ok, rv_err = False, str(e)
check(rv_ok, "run_verb(print_check) is accepted on a selected body%s" % ("" if rv_ok else ": " + rv_err))
ins = safe_call("ui.inspect")
pn = ins.get("print_notes") if isinstance(ins, dict) else None
check(isinstance(pn, list) and len(pn) == len(notes_of(res)),
      "the sidebar Print check section lists one row per note (shared state with the pins)")

# --- Negative: bore Ø8 gives no thin_wall --------------------------------------------------
res8 = box_with_bore(8.0)
tw8 = thin_walls(res8)
check(res8.get("ok") is True, "analyze_printability runs on the Ø8 bore box")
check(len(tw8) == 0, "a Ø8 horizontal bore yields NO thin_wall note (lid is ~6 mm)")
w8 = res8.get("warnings", []) if isinstance(res8, dict) else []
check(not any(("thinnest" in w or "walls thinner" in w) for w in w8),
      "the Ø8 bore emits no thin-wall warning text")

# --- Negative: no notes -> side list empty/hidden ------------------------------------------
call("new_document")
call("extrude_rect", width=20, height=20, distance=10)
time.sleep(0.4)
call("ui.click", at=[top["x"], top["y"]])
time.sleep(0.4)
try:
    call("run_verb", verb="print_check")
    rv2 = True
except RuntimeError:
    rv2 = False
ins = safe_call("ui.inspect")
pn = ins.get("print_notes") if isinstance(ins, dict) else None
check(isinstance(pn, list) and len(pn) == 0,
      "a part with no notes leaves the side-list data empty (section hidden)")

# --- Postcondition 5 (uiv8): global (pin-less) notes ---------------------------------------
call("new_document")
call("extrude_rect", width=20, height=20, distance=10)          # body 0
call("extrude_rect", width=20, height=20, distance=10)          # body 1, same footprint
call("transform", body=1, dx=20.1)                              # 0.1 mm gap -> a tight pair
time.sleep(0.4)
resT = safe_call("analyze_printability", body=0)
sugs = resT.get("suggestions", []) if isinstance(resT, dict) else []
tight = [n for n in notes_of(resT) if n.get("kind") == "tight_pair"]   # a tight pair is a warning and a pin-less note, not a suggestion
check(len(tight) >= 1, "two boxes 0.1 mm apart produce a tight_pair suggestion")
glob_notes = [n for n in notes_of(resT) if n.get("at") is None and n.get("kind") == "tight_pair"]
check(len(glob_notes) >= 1,
      "the tight_pair (and orientation) suggestions are emitted as pin-less notes with at==null")

print("CHECKS %d FAILED %d" % (_checks, len(fails)))
sys.exit(1 if fails else 0)
