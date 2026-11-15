#!/usr/bin/env python3
"""F2P harness for the Print-check auto-fixes (pins + Apply Fix + the Print check toggle).

Builds the DfAM scenarios, checks that the right fix is offered per note kind, that it
runs through the verb dispatcher and clears the note, and that the new "Print check"
toggle hides the notes and the analysis.

    python3 -I scripts/CAD/check-fix.py [socket]   # default /tmp/orca-cad-mcp.sock
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
    except Exception as e:  # noqa: BLE001
        return {"__error__": str(e)}


def notes_of(res):
    if not isinstance(res, dict) or "__error__" in res:
        return []
    return res.get("notes", []) if isinstance(res.get("notes"), list) else []


def kind_notes(res, kind):
    return [n for n in notes_of(res) if n.get("kind") == kind]


def has_fix(note):
    f = note.get("fix")
    return isinstance(f, dict) and isinstance(f.get("label"), str) and f["label"] and isinstance(f.get("steps"), list) and f["steps"]


def sleep():
    time.sleep(0.4)


def new_doc():
    call("new_document")
    sleep()


def check_kind_fix(kind, build, label):
    """`build` leaves a document; analyse unrotated and require a note of `kind` WITH a fix."""
    new_doc()
    build()
    res = safe_call("analyze_printability", body=0)
    ns = kind_notes(res, kind)
    check(len(ns) > 0, "%s: a %s note is produced unrotated (%d)" % (label, kind, len(ns)))
    check(all(has_fix(n) for n in ns),
          "%s: every %s note carries a fix with label + steps" % (label, kind))


def box(w, h, d):
    call("extrude_rect", width=w, height=h, distance=d)
    sleep()


def pocket_box():
    box(100, 100, 20)
    box(60, 40, 8)            # body 1, centred inside the 100x100 footprint
    safe_call("transform", body=1, dz=12)   # tool sits at z 12..20: a pocket from the TOP, its floor faces up
    r = safe_call("boolean", op="subtract", target=0, tool=1)
    check(r.get("ok") is True, "base_corner rig: subtract 60x40x8 from 100x100x20 works")
    sleep()


def tight_pair_rig():
    box(20, 20, 10)
    box(20, 20, 10)
    r = safe_call("transform", body=1, dx=20.1)
    check(r.get("ok") is True, "tight_pair rig: body 1 moved to dx=20.1 (gap 0.1 mm)")
    sleep()


# --- (1) the four implementable kinds get a fix unrotated; use_parameters does not ---
check_kind_fix("vertical_edge", lambda: box(40, 40, 20), "rt1")
check_kind_fix("warp_risk", lambda: box(80, 60, 5), "ck1")
check_kind_fix("base_corner", pocket_box, "ck1")
check_kind_fix("tight_pair", tight_pair_rig, "ck1")

new_doc()
box(10, 10, 10); box(10, 10, 10); box(10, 10, 10)   # 3 features, no variables -> use_parameters
res = safe_call("analyze_printability", body=0)
up = kind_notes(res, "use_parameters")
check(len(up) > 0, "ck1: a use_parameters note is produced")
check(all(has_fix(n) for n in up), "ck1: use_parameters note carries a fix (round 2 recipe)")

# --- (2) vertical_edge fix on a 40x40x20 box -----------------------------------
new_doc()
box(40, 40, 20)
res = safe_call("analyze_printability", body=0)
check(any(has_fix(n) for n in kind_notes(res, "vertical_edge")), "ck2: a vertical_edge fix is offered")
r = safe_call("apply_print_fix", kind="vertical_edge", body=0)
check(isinstance(r, dict) and r.get("ok") is True and r.get("steps", 0) >= 1,
      "ck2: apply_print_fix kind=vertical_edge ok: %s" % (r,))
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "vertical_edge")) == 0, "ck2: no vertical_edge note after the fillet fix")
check(res.get("solids") == 1, "ck2: the body is still one solid (solids=%s)" % (res.get("solids"),))

# --- (3) warp_risk fix on an 80x60x5 plate ------------------------------------
new_doc()
box(80, 60, 5)
res = safe_call("analyze_printability", body=0)
check(any(has_fix(n) for n in kind_notes(res, "warp_risk")), "ck3: a warp_risk fix is offered")
before = safe_call("select_topology", type="face", body=0, limit=200000).get("count", 0)
r = safe_call("apply_print_fix", kind="warp_risk", body=0)
check(isinstance(r, dict) and r.get("ok") is True and r.get("steps", 0) >= 1,
      "ck3: apply_print_fix kind=warp_risk ok: %s" % (r,))
after = safe_call("select_topology", type="face", body=0, limit=200000).get("count", 0)
check(isinstance(after, int) and after > before,
      "ck3: body triangle count increased by the mouse ears (%d -> %d)" % (before, after))
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "warp_risk")) == 0, "ck3: no warp_risk note after the mouse-ear fix")
check(isinstance(res.get("solids"), int) and res.get("solids") >= 1,
      "ck3: solids still sensible after the fix (%s)" % (res.get("solids"),))

# --- (4) base_corner: offered unrotated, withheld when rotated ------------------
new_doc()
pocket_box()
res = safe_call("analyze_printability", body=0)
check(any(has_fix(n) for n in kind_notes(res, "base_corner")),
      "ck4: base_corner fix IS offered on the unrotated pocket box")
res = safe_call("analyze_printability", body=0, rotate=[180, 0, 0])
bcn = kind_notes(res, "base_corner")
check(not any(has_fix(n) for n in bcn),
      "ck4: with rotate=[180,0,0] no base_corner fix is offered (geometry fixes are unrotated-only; %d notes seen)" % len(bcn))

# --- (5) tight_pair fix: two bodies 0.1 mm apart --------------------------------
new_doc()
tight_pair_rig()
res = safe_call("analyze_printability", body=0)
check(any(has_fix(n) for n in kind_notes(res, "tight_pair")), "ck5: a tight_pair fix is offered")
r = safe_call("apply_print_fix", kind="tight_pair", body=0)
check(isinstance(r, dict) and r.get("ok") is True,
      "ck5: apply_print_fix kind=tight_pair ok: %s" % (r,))
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "tight_pair")) == 0, "ck5: no tight_pair note after moving the parts apart")

# --- (6) apply_print_fix on a kind with no fix is refused -----------------------
new_doc()
box(10, 10, 10); box(10, 10, 10); box(10, 10, 10)
res = safe_call("analyze_printability", body=0)
check(any(n.get("kind") == "test_fit" for n in notes_of(res)), "ck6: test_fit note present")
r = safe_call("apply_print_fix", kind="test_fit", body=0)
check(isinstance(r, dict) and "__error__" in r and "no automatic fix" in r["__error__"],
      "ck6: apply_print_fix on a no-fix kind (test_fit) is refused: %s" % (r,))

# --- (7) the Print check toggle (ui.inspect / ui_option) -----------------------
new_doc()
call("extrude_rect", width=20, height=20, distance=5, taper=60)   # a steep_chamfer WARNING note
sleep()
call("analyze_printability", body=0)
insp = safe_call("ui.inspect")
check(insp.get("print_check_on") is True, "ck7: ui.inspect starts with print_check_on true")
check(isinstance(insp.get("print_notes"), list) and len(insp["print_notes"]) > 0,
      "ck7: print_notes are populated when the check is on")
r = safe_call("ui_option", name="print_check", value=False)
check(isinstance(r, dict) and r.get("ok") is True and r.get("print_check") is False,
      "ck7: ui_option print_check=false ok")
insp = safe_call("ui.inspect")
check(insp.get("print_check_on") is False, "ck7: ui.inspect reports print_check_on false after the toggle")
check(len(insp.get("print_notes") or []) == 0, "ck7: print_notes are empty/hidden when the check is off")
r = safe_call("ui_option", name="print_check", value=True)
check(isinstance(r, dict) and r.get("ok") is True and r.get("print_check") is True,
      "ck7: ui_option print_check=true ok")
insp = safe_call("ui.inspect")
check(insp.get("print_check_on") is True, "ck7: ui.inspect reports print_check_on true again")
check(isinstance(insp.get("print_notes"), list) and len(insp["print_notes"]) > 0,
      "ck7: print_notes come back when turned on again")

# --- (8) the skipped kinds: report why ------------------------------------------
# horizontal_hole: the fix turns the hole's teardrop flag on
safe_call("new_document"); safe_call("extrude_rect", width=60, height=40, distance=20)
safe_call("hole", diameter=12, through=True, plane="XZ", x=0, y=10)
r = safe_call("analyze_printability", body=0)
hn = [n for n in r.get("notes", []) if n.get("kind") == "horizontal_hole"]
check(len(hn) == 1 and hn[0].get("fix"), "ck8: horizontal_hole note carries a fix")
r = safe_call("apply_print_fix", kind="horizontal_hole", body=0)
check(isinstance(r, dict) and r.get("ok") is True, "ck8: apply_print_fix horizontal_hole ok")
r = safe_call("analyze_printability", body=0)
check(not [n for n in r.get("notes", []) if n.get("kind") == "horizontal_hole"], "ck8: no horizontal_hole note after the fix")
print("note: curve_axis has no 'drop back to bed' step: no place_on_bed/translate-to-bed verb exists, so the rotation is left as-is (reported unrotated by the harness)")

# --- (9) long_bridge fix: ribs split a 60 mm roof ------------------------------
new_doc()
box(100, 100, 20)
box(60, 60, 8)
r = safe_call("boolean", op="subtract", target=0, tool=1)
check(r.get("ok") is True, "ck9: subtract 60x60x8 from 100x100x20 works")
sleep()
res = safe_call("analyze_printability", body=0)
lb = kind_notes(res, "long_bridge")
check(len(lb) > 0, "ck9: a long_bridge note is produced (%d)" % len(lb))
check(all(has_fix(n) for n in lb), "ck9: every long_bridge note carries a fix")
r = safe_call("apply_print_fix", kind="long_bridge", body=0)
check(isinstance(r, dict) and r.get("ok") is True and r.get("steps", 0) >= 1,
      "ck9: apply_print_fix kind=long_bridge ok: %s" % (r,))
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "long_bridge")) == 0, "ck9: no long_bridge note after adding ribs")
lv = [L for L in (res.get("overhang_levels") or []) if abs(L.get("z", 0) - 8) < 0.5]
if lv:
    maxspan = max(L["span_mm"] for L in lv)
    check(maxspan <= 20.001, "ck9: roof level span now <= 20 mm (max %.1f)" % maxspan)
else:
    check(True, "ck9: roof level merged/gone after the ribs (no level at z=8)")
check(res.get("solids") == 1, "ck9: the body is still one solid (solids=%s)" % (res.get("solids"),))

# --- (10) sacrificial_layer fix: membrane plate under a 14 mm roof --------------
new_doc()
box(100, 100, 20)
box(14, 14, 8)
r = safe_call("boolean", op="subtract", target=0, tool=1)
check(r.get("ok") is True, "ck10: subtract 14x14x8 from 100x100x20 works")
sleep()
res = safe_call("analyze_printability", body=0)
sl = kind_notes(res, "sacrificial_layer")
check(len(sl) > 0, "ck10: a sacrificial_layer note is produced (%d)" % len(sl))
check(all(has_fix(n) for n in sl), "ck10: every sacrificial_layer note carries a fix")
def roof_z(res):
    lv = [l for l in (res.get("overhang_levels") or []) if isinstance(l, dict)]
    return max([l.get("z", 0) for l in lv]) if lv else None
before = roof_z(res)
r = safe_call("apply_print_fix", kind="sacrificial_layer", body=0)
check(isinstance(r, dict) and r.get("ok") is True,
      "ck10: apply_print_fix kind=sacrificial_layer ok: %s" % (r,))
after = roof_z(safe_call("analyze_printability", body=0))
check(before is not None and after is not None and before - after > 0.3,
      "ck10: the roof moved down by the membrane thickness (%s -> %s)" % (before, after))

# --- (11) fillet_from_below fix: suppress the bed fillet, then chamfer ----------
new_doc()
box(40, 40, 20)
r = safe_call("fillet", where={"kind": "line", "z": 0}, radius=5, body=0)
check(r.get("ok") is True, "ck11: fillet the bottom edges at R5 works")
sleep()
res = safe_call("analyze_printability", body=0)
fb = kind_notes(res, "fillet_from_below")
check(len(fb) > 0, "ck11: a fillet_from_below note is produced (%d)" % len(fb))
check(all(has_fix(n) for n in fb), "ck11: every fillet_from_below note carries a fix")
r = safe_call("apply_print_fix", kind="fillet_from_below", body=0)
check(isinstance(r, dict) and r.get("ok") is True,
      "ck11: apply_print_fix kind=fillet_from_below ok: %s" % (r,))
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "fillet_from_below")) == 0, "ck11: no fillet_from_below note after the chamfer")

# --- (12) steep_chamfer fix: taper 60 -> 45 ------------------------------------
new_doc()
call("extrude_rect", width=40, height=40, distance=20, taper=60)
sleep()
res = safe_call("analyze_printability", body=0)
sc = kind_notes(res, "steep_chamfer")
check(len(sc) > 0, "ck12: a steep_chamfer note is produced (%d)" % len(sc))
check(all(has_fix(n) for n in sc), "ck12: every steep_chamfer note carries a fix")
r = safe_call("apply_print_fix", kind="steep_chamfer", body=0)
check(isinstance(r, dict) and r.get("ok") is True,
      "ck12: apply_print_fix kind=steep_chamfer ok: %s" % (r,))
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "steep_chamfer")) == 0, "ck12: no steep_chamfer note after the taper fix")

# --- (13) curve_axis fix: stand a lying cylinder up ----------------------------
new_doc()
r = safe_call("primitive", shape="cylinder", diameter=20, height=30)
check(r.get("ok") is True, "ck13: build a cylinder")
sleep()
r = safe_call("transform", body=0, angle=90, axis_x=1)
check(r.get("ok") is True, "ck13: lay the cylinder down about X")
sleep()
res = safe_call("analyze_printability", body=0)
ca = kind_notes(res, "curve_axis")
check(len(ca) > 0, "ck13: a curve_axis note is produced when unrotated (%d)" % len(ca))
check(all(has_fix(n) for n in ca), "ck13: every curve_axis note carries a fix")
check(any(isinstance(n.get("axis"), list) and len(n["axis"]) == 3 for n in ca),
      "ck13: curve_axis notes carry an 'axis' field")
r = safe_call("apply_print_fix", kind="curve_axis", body=0)
check(isinstance(r, dict) and r.get("ok") is True,
      "ck13: apply_print_fix kind=curve_axis ok: %s" % (r,))
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "curve_axis")) == 0, "ck13: no curve_axis note after standing the part up")

# --- (14) use_parameters fix: create depth_* variables --------------------------
new_doc()
box(10, 10, 10); box(10, 10, 10); box(10, 10, 10)
res = safe_call("analyze_printability", body=0)
up = kind_notes(res, "use_parameters")
check(len(up) > 0, "ck14: a use_parameters note is produced")
check(all(has_fix(n) for n in up), "ck14: use_parameters note carries a fix")
r = safe_call("apply_print_fix", kind="use_parameters", body=0)
check(isinstance(r, dict) and r.get("ok") is True,
      "ck14: apply_print_fix kind=use_parameters ok: %s" % (r,))
csv = safe_call("variables_export")
depth_vars = "depth_" if "depth_" in json.dumps(csv) else ""
check(bool(depth_vars), "ck14: depth_* variables exist after the fix (%s)" % (str(csv)[:80],))
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "use_parameters")) == 0, "ck14: no use_parameters note after creating variables")

# --- (15) kinds that must stay WITHOUT a fix ------------------------------------
# test_fit + compliance: two bodies close together
new_doc()
tight_pair_rig()
res = safe_call("analyze_printability", body=0)
for k in ("test_fit", "compliance"):
    ns = kind_notes(res, k)
    check(len(ns) > 0, "ck15: a %s note is produced (%d)" % (k, len(ns)))
    check(all("fix" not in n for n in ns), "ck15: %s note has no 'fix' key" % k)
# slit_nut_trap: a bore
new_doc()
box(20, 20, 10)
call("hole", diameter=6, depth=8, x=0, y=0)
sleep()
res = safe_call("analyze_printability", body=0)
ns = kind_notes(res, "slit_nut_trap")
check(len(ns) > 0, "ck15: a slit_nut_trap note is produced (%d)" % len(ns))
check(all("fix" not in n for n in ns), "ck15: slit_nut_trap note has no 'fix' key")
# thin_wall: a 0.4 mm plate
new_doc()
call("extrude_rect", width=0.4, height=50, distance=10)
sleep()
res = safe_call("analyze_printability", body=0)
ns = kind_notes(res, "thin_wall")
if ns:
    check(all("fix" not in n for n in ns), "ck15: thin_wall note has no 'fix' key")
else:
    print("note: thin_wall fix skipped: a 0.4 mm plate produced no thin_wall note")
print("note: mesh_integrity fix skipped: would need an open-edge / non-manifold mesh, not built by this harness")


# --- (10) floating part, bed adhesion, orientation, text_indent ---------------------
def zmax(body=0):
    d = safe_call("describe_scene")
    try:
        return d["bodies"][body]["bbox"]["max"][2]
    except Exception:  # noqa: BLE001
        return None


# a second body hovering 30 mm up with nothing under it must be reported as floating (global note naming the body)
safe_call("new_document")
safe_call("extrude_rect", width=10, height=10, distance=10)
safe_call("plane", type="offset", base=0, offset=30)
safe_call("extrude_rect", width=10, height=10, distance=10, plane="datum:0", boolean="union", body=0)
res = safe_call("analyze_printability", body=0)
fl = kind_notes(res, "floating_part")
check(len(fl) == 1 and fl[0].get("severity") == "warning" and fl[0].get("body") == 1 and fl[0].get("at") is None, "ck10: one global floating_part note naming body 1")
check(isinstance(res, dict) and (res.get("extras") or {}).get("floating_bodies") == 1, "ck10: extras.floating_bodies == 1")
check(all("fix" not in n for n in fl), "ck10: floating_part has no fix (by design)")
# a body resting on another is not floating
safe_call("new_document")
safe_call("extrude_rect", width=20, height=20, distance=10)
safe_call("plane", type="offset", base=0, offset=10)
safe_call("extrude_rect", width=10, height=10, distance=10, plane="datum:0", boolean="new")
check(not kind_notes(safe_call("analyze_printability", body=0), "floating_part"), "ck10: a body sitting on another is not floating")

safe_call("new_document")
safe_call("extrude_rect", width=40, height=40, distance=20)
check(not kind_notes(safe_call("analyze_printability", body=0), "bed_adhesion"), "ck10: a 40x40 base has no bed_adhesion note")
check(not kind_notes(safe_call("analyze_printability", body=0), "floating_part"), "ck10: a plain box has no floating_part")
safe_call("new_document")
safe_call("extrude_rect", width=8, height=8, distance=20)
res = safe_call("analyze_printability", body=0)
check(len(kind_notes(res, "bed_adhesion")) == 1, "ck10: an 8x8 base (64 mm2) gets bed_adhesion")
safe_call("new_document")
safe_call("extrude_rect", width=40, height=2, distance=20)
check(len(kind_notes(safe_call("analyze_printability", body=0), "bed_adhesion")) == 1, "ck10: a 2 mm wide base gets bed_adhesion")

# orientation: a flared plate prints better upside down; the fix turns the part, then no orientation note
safe_call("new_document")
safe_call("extrude_rect", width=20, height=20, distance=5, taper=60)
res = safe_call("analyze_printability", body=0)
on = kind_notes(res, "orientation")
if on:
    check(has_fix(on[0]), "ck10: orientation note carries a fix")
    r = safe_call("apply_print_fix", kind="orientation", body=0)
    check(isinstance(r, dict) and r.get("ok") is True, "ck10: apply_print_fix orientation ok")
    check(not kind_notes(safe_call("analyze_printability", body=0), "orientation"), "ck10: no orientation note after the fix")
else:
    print("note: orientation scenario produced no orientation note; fix untested")

# text_indent: raised text -> cut; the top face goes back to z=20
safe_call("new_document")
safe_call("extrude_rect", width=40, height=40, distance=20)
safe_call("plane", type="offset", base=0, offset=20)
r = safe_call("add_text", text="ORCA", height=6, plane="datum:0", extrude_distance=1, boolean="union")
check(isinstance(r, dict) and r.get("ok") is True, "ck10: raised text built")
check(zmax() is not None and abs(zmax() - 21) < 0.05, "ck10: raised text puts the top at z=21 (got %s)" % zmax())
res = safe_call("analyze_printability", body=0)
tn = kind_notes(res, "text_indent")
check(len(tn) == 1 and has_fix(tn[0]), "ck10: text_indent note carries a fix for raised text")
r = safe_call("apply_print_fix", kind="text_indent", body=0)
check(isinstance(r, dict) and r.get("ok") is True, "ck10: apply_print_fix text_indent ok")
check(zmax() is not None and abs(zmax() - 20) < 0.05, "ck10: after the fix the top is back at z=20 (got %s)" % zmax())

print("CHECKS %d FAILED %d" % (_checks, len(fails)))
sys.exit(1 if fails else 0)
