#!/usr/bin/env python3
"""F2P harness for DfAM tips 5/7/16/11/18/22/23/24 (dfam_extras additions).

Covers the mesh-based print-frame checks (vertical_edge for sharp convex edges,
base_corner for the concave wall+floor junction of an up-facing pocket, curve_axis
for cylinder-like surfaces tilted from Z) and the pin-less global design advice
(use_parameters / slit_nut_trap / test_fit / compliance). text_indent (tip 24)
is not exercised: no MCP verb builds a CAD text feature (ui.text only types into a
window), so it is skipped and reported here.

    python3 -I scripts/CAD/check-tips2.py [socket]   # default /tmp/orca-cad-mcp.sock
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


def extras_of(res):
    if not isinstance(res, dict) or "__error__" in res:
        return {}
    e = res.get("extras")
    return e if isinstance(e, dict) else {}


def kind_notes(res, kind):
    return [n for n in notes_of(res) if n.get("kind") == kind]


ADVICE = {"use_parameters", "slit_nut_trap", "test_fit", "compliance", "text_indent"}

# --- (a) 40x40x20 box: four sharp convex vertical edges -----------------------
call("new_document")
call("extrude_rect", width=40, height=40, distance=20)
time.sleep(0.5)
res = call("analyze_printability", body=0)
ve = kind_notes(res, "vertical_edge")
check(len(ve) == 1, "the 40x40x20 box yields one vertical_edge note")
check(ve and ve[0].get("severity") == "suggestion", "the vertical_edge note has severity suggestion")
check(extras_of(res).get("vertical_edges") == 4,
      "extras.vertical_edges == 4 (got %s)" % (extras_of(res).get("vertical_edges"),))
check(bool(ve) and isinstance(ve[0].get("tris"), list) and len(ve[0]["tris"]) > 0,
      "the vertical_edge note carries tris[]")
check(bool(ve) and isinstance(ve[0].get("normal"), list) and len(ve[0]["normal"]) == 3,
      "the vertical_edge note carries a normal")
sugs = res.get("suggestions", []) if isinstance(res, dict) else []
check(any(x.get("kind") == "vertical_edge_fillet" for x in sugs),
      "a vertical_edge_fillet suggestion is listed")

# --- (b) same box with the four vertical edges filleted: no vertical_edge ------
call("new_document")
call("extrude_rect", width=40, height=40, distance=20)
time.sleep(0.5)
ff = safe_call("fillet", where={"kind": "line", "parallel": "z"}, radius=2.0, body=0)
time.sleep(0.4)
res = safe_call("analyze_printability", body=0)
check(kind_notes(res, "vertical_edge") == [],
      "filleting the four vertical edges removes the vertical_edge note (%s)" % (ff,))

# --- (c) 20x20x6 box (height < 10): no vertical_edge --------------------------
call("new_document")
call("extrude_rect", width=20, height=20, distance=6)
time.sleep(0.5)
res = call("analyze_printability", body=0)
check(kind_notes(res, "vertical_edge") == [],
      "a 20x20x6 box (height<10) yields no vertical_edge note")

# --- (d) base_corner: pocket cut from the bottom, analysed both ways -----------
call("new_document")
call("extrude_rect", width=100, height=100, distance=20)
time.sleep(0.5)
call("extrude_rect", width=60, height=40, distance=8, boolean="subtract", body=0)
time.sleep(0.5)
resR = safe_call("analyze_printability", body=0, rotate=[180, 0, 0])
bc = kind_notes(resR, "base_corner")
check(len(bc) >= 1, "the pocket part analysed upside-down yields a base_corner note")
check((extras_of(resR).get("base_corners") or 0) >= 1,
      "extras.base_corners >= 1 (got %s)" % (extras_of(resR).get("base_corners"),))
check(bc and bc[0].get("severity") == "suggestion", "the base_corner note is a suggestion")
check(bool(bc) and isinstance(bc[0].get("normal"), list) and len(bc[0]["normal"]) == 3,
      "the base_corner note carries a normal")
resU = safe_call("analyze_printability", body=0)
check(kind_notes(resU, "base_corner") == [],
      "the same pocket part analysed unrotated yields no base_corner note (pocket ceiling faces down)")

# --- (e) curve_axis: cylinder standing vs on its side -------------------------
call("new_document")
call("extrude_circle", diameter=30, distance=40)
time.sleep(0.5)
res = call("analyze_printability", body=0)
check(kind_notes(res, "curve_axis") == [],
      "a standing cylinder (axis along Z) yields no curve_axis note")
resS = safe_call("analyze_printability", body=0, rotate=[90, 0, 0])
ca = kind_notes(resS, "curve_axis")
check(len(ca) >= 1, "the same cylinder on its side yields a curve_axis note")
check(bool(ca) and "axis" in ca[0].get("text", ""), "the curve_axis text mentions the axis")
check((extras_of(resS).get("curve_axes") or 0) >= 1,
      "extras.curve_axes >= 1 (got %s)" % (extras_of(resS).get("curve_axes"),))

# --- (f) design advice: use_parameters / slit_nut_trap / test_fit / compliance -
call("new_document")
call("extrude_rect", width=20, height=20, distance=10)
time.sleep(0.4)
res = call("analyze_printability", body=0)
check(kind_notes(res, "use_parameters") == [],
      "a fresh box with 2 features and no variables yields no use_parameters advice")
call("hole", diameter=5, through=True, plane="XY", x=0, y=0)
time.sleep(0.4)
res = call("analyze_printability", body=0)
check(len(kind_notes(res, "use_parameters")) >= 1,
      "adding a hole (>=3 features, no variables) fires use_parameters")
check(len(kind_notes(res, "slit_nut_trap")) >= 1,
      "a document with a hole fires slit_nut_trap")

call("new_document")
call("extrude_rect", width=20, height=20, distance=10)
call("extrude_rect", width=20, height=20, distance=10)
time.sleep(0.4)
res = call("analyze_printability", body=0)
check(len(kind_notes(res, "test_fit")) >= 1, "two bodies fire test_fit")
call("transform", body=1, dx=20.1)
time.sleep(0.4)
res = call("analyze_printability", body=0)
check(len(kind_notes(res, "compliance")) >= 1,
      "two bodies 0.1 mm apart fire compliance")

for n in notes_of(res):
    if n.get("kind") in ADVICE:
        check(n.get("at") is None, "the %s advice note has at==null" % (n.get("kind"),))
        check("normal" not in n and "tris" not in n, "the %s advice note carries no normal/tris" % (n.get("kind"),))
ta = extras_of(res).get("tips_advice")
check(isinstance(ta, list) and "compliance" in ta,
      "extras.tips_advice lists the fired advice kinds (%s)" % (ta,))

# text_indent (tip 24): a Text feature (add_text verb) fires the global advice note.
call("new_document")
call("extrude_rect", width=40, height=40, distance=20)
call("add_text", text="Hi", height=6, plane="XY")
time.sleep(0.4)
res = call("analyze_printability", body=0)
ti = kind_notes(res, "text_indent")
check(len(ti) >= 1, "a document with a text feature fires text_indent")
check(bool(ti) and ti[0].get("at") is None and "tris" not in ti[0], "the text_indent note is pin-less")

print("CHECKS %d FAILED %d" % (_checks, len(fails)))
sys.exit(1 if fails else 0)
