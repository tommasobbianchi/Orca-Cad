#!/usr/bin/env python3
"""F2P harness for the headless `add_text` verb (DfAM text).

The verb is the MCP twin of the GUI Text dialog: it builds a Text sketch feature
(and optionally extrudes it) with no dialog, so an agent can drive it. These checks
cover the feature appearing + no dialog left open, raised text (union on a datum
plane), engraved text (subtract, two_sided, on a datum plane offset from XZ), the
error paths, and the busy gate when a sketch is open.

    python3 -I scripts/CAD/check-text.py [socket]   # default /tmp/orca-cad-mcp.sock
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


def body_volume(body=0):
    p = safe_call("mass_properties", body=body)
    if not isinstance(p, dict) or "__error__" in p or not p.get("valid"):
        return None
    return p.get("volume")


def body_surface(body=0):
    p = safe_call("mass_properties", body=body)
    if not isinstance(p, dict) or "__error__" in p or not p.get("valid"):
        return None
    return p.get("surface_area")


# --- (a) a lone Text sketch appears as a feature, and no dialog/card is left open -------
call("new_document")
call("extrude_rect", width=40, height=40, distance=20)
time.sleep(0.5)
r = safe_call("add_text", text="ORCA", height=8, plane="XY")
check(r.get("ok") is True and "text_index" in r and r.get("error") == "",
      "add_text on plane XY makes a Text sketch: %s" % (r,))
scene = safe_call("describe_scene")
names = [f.get("name", "") for f in (scene.get("features") or []) if isinstance(f, dict)]
check(any(("Text" in n or "Testo" in n) for n in names),
      "describe_scene lists a Text feature (names=%s)" % (names,))
insp = safe_call("ui.inspect")
card = insp.get("card") or {}
check(card.get("tool") == 0 and "__error__" not in insp,
      "no card/dialog is open after add_text (ui.inspect card=%s)" % (card,))

# --- (b) raised text: union extrude on a datum plane on top of a plate -------------------
call("new_document")
call("extrude_rect", width=40, height=40, distance=5)
call("plane", type="offset", base=0, offset=5)   # datum:0 = the plate's top face
time.sleep(0.5)
v0 = body_volume(0)
s0 = body_surface(0)
r = safe_call("add_text", text="ORCA", height=6, plane="datum:0", extrude_distance=1, boolean="union")
check(r.get("ok") is True and "extrude_index" in r and r.get("error") == "",
      "add_text height=6 union extrude on plate top succeeds: %s" % (r,))
v1, s1 = body_volume(0), body_surface(0)
check(v0 is not None and v1 is not None and v1 > v0,
      "raised text ADDS material: volume %.3f -> %.3f" % (v0 or 0, v1 or 0))
check(s0 is not None and s1 is not None and s1 > s0,
      "raised text grows the surface: %.3f -> %.3f" % (s0 or 0, s1 or 0))
ap = safe_call("analyze_printability", body=0)
check(ap.get("ok") is True, "analyze_printability still ok on the raised-text plate")

# --- (c) engraved text: subtract, two_sided, on a datum offset from XZ --------------------
call("new_document")
call("extrude_rect", width=40, height=40, distance=20)   # box, top face at y=20
call("plane", type="offset", base=1, offset=20)           # datum:0 = XZ shifted to y=20
time.sleep(0.5)
v0 = body_volume(0)
r = safe_call("add_text", text="ORCA", height=6, plane="datum:0",
              extrude_distance=1.5, end="two_sided", distance2=1.5, boolean="subtract")
check(r.get("ok") is True and "extrude_index" in r and r.get("error") == "",
      "engraved text (subtract, two_sided) on the box top succeeds: %s" % (r,))
v1 = body_volume(0)
check(v0 is not None and v1 is not None and v1 < v0,
      "engraving REMOVES material: volume %.3f -> %.3f" % (v0 or 0, v1 or 0))
ap = safe_call("analyze_printability", body=0)
check(any(n.get("kind") == "text_indent" for n in notes_of(ap)),
      "analyze_printability notes a text_indent note (notes=%s)" % (notes_of(ap),))

# --- (d) error paths: empty text, height 0, unknown plane --------------------------------
e = safe_call("add_text", text="")
check("__error__" in e and e["__error__"], "empty text is refused: %s" % (e,))
e = safe_call("add_text", text="ORCA", height=0)
check("__error__" in e and e["__error__"] and "height" in e["__error__"],
      "height=0 is refused: %s" % (e,))
e = safe_call("add_text", text="ORCA", plane="bogus")
check("__error__" in e and e["__error__"], "unknown plane is refused: %s" % (e,))

# --- (e) busy gate: refused while a sketch is open --------------------------------------
call("new_document")
call("sketch_begin", plane="XY")
e = safe_call("add_text", text="ORCA")
check("__error__" in e and e["__error__"], "add_text is refused with a sketch open: %s" % (e,))
call("sketch_cancel")

print("CHECKS %d FAILED %d" % (_checks, len(fails)))
sys.exit(1 if fails else 0)
