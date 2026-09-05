#!/usr/bin/env python3
"""The click-edit contract: a value field that opens must accept what is TYPED into it.

WHY THIS EXISTS SEPARATELY FROM check-gui-sketching.py. That ladder draws geometry and grades the
result, and to make its values land it calls focus_field() — one synthetic click INTO the field
before typing. Its own docstring says why:

    WITHOUT THIS THE TYPED VALUE IS SILENTLY DISCARDED. The field is shown and raised but the
    window manager does not give it the keyboard, so xdotool's digits go to the canvas and Return
    commits the value the field opened with — the pre-filled as-drawn number.

That click is a workaround for a defect, and a suite that performs it can never see the defect
again. A user cannot be told to click the field first; when they do not, they get the as-drawn
number and report "the label value is not editable". So this ladder types IMMEDIATELY after the
field opens, exactly as a person does, and fails if the prefill is what gets committed.

WHAT IT GRADES. The app emits one line per event under SNAPORCA_UXTRACE=1:

    [UX] open    title=Length prefill=154.76
    [UX] commit  title=Length typed=80 value=80.0000
    [UX] refused title=Length typed=8O
    [UX] cancel  title=Length

For every field the driver opens it asserts: a commit arrived, what the field received is what we
typed, the parsed value equals it, and it differs from the prefill. The last clause is the one
that matters — a field that is on screen but deaf commits its prefill, and every other signal
(the field is visible, a constraint is created, the solve succeeds) looks perfectly healthy.

    scripts/CAD/check-gui-click-edit.py --display :10 --bin build/src/Release/orca-slicer

With --attach it drives an already-running app instead of launching one; the app must have been
started with SNAPORCA_UXTRACE=1 and its stderr redirected to --trace.
Exit 0 = every field took what was typed.
"""
import argparse, json, os, re, shutil, signal, subprocess, sys, tempfile, time

AP = argparse.ArgumentParser()
AP.add_argument("--display", default=os.environ.get("DISPLAY", ":10"))
AP.add_argument("--bin", default="build/src/Release/orca-slicer")
AP.add_argument("--datadir", default="")
AP.add_argument("--trace", default="")
AP.add_argument("--attach", action="store_true", help="drive a running app; do not launch one")
AP.add_argument("--keep", action="store_true", help="leave the app running afterwards")
AP.add_argument("--seed-from", default=os.path.expanduser("~/.config/OrcaCAD/OrcaSlicer.conf"),
                help="an existing OrcaSlicer.conf to copy presets/settings from")
A = AP.parse_args()

DISP = A.display
TRACE = A.trace or os.path.join(tempfile.gettempdir(), "ux-click-edit.log")
_fail = 0
_checks = 0


def sh(cmd):
    # bash -c, NOT -lc: a login shell sources the profile on every xdotool call, and this driver
    # makes hundreds. On a GNOME box that meant im-config running per call, thousands of journal
    # lines, and a window poll slow enough to time out before the app had finished starting.
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True).stdout


def xdo(args):
    sh(f"DISPLAY={DISP} xdotool {args}")


def key(k, pause=0.35):
    xdo(f"key {k}")
    time.sleep(pause)


def typ(s, pause=0.35):
    # --clearmodifiers so a modifier left down by an earlier synthetic key cannot turn digits
    # into something else; --delay 60 because ImGui reads one character per frame.
    xdo(f"type --clearmodifiers --delay 60 -- '{s}'")
    time.sleep(pause)


def die(msg):
    print(f"FATAL {msg}", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- the app

_proc = None


def seed_datadir(datadir):
    """The Design tab does not exist unless enable_cad_feature is on, and it needs a RESTART.

    A fresh datadir has it off, so a driver that just points the app at an empty directory gets
    Prepare/Preview/Device/Project, no Design tab, and every rung fails for a reason that has
    nothing to do with what is being tested. Seed the flag before the first launch.
    """
    os.makedirs(datadir, exist_ok=True)
    conf = os.path.join(datadir, "OrcaSlicer.conf")
    data = {}
    if os.path.exists(A.seed_from):
        try:
            with open(A.seed_from) as f:
                data = json.load(f)
        except Exception:
            data = {}
    app = data.setdefault("app", {})
    app["enable_cad_feature"] = True
    # Deterministic starting state for the rungs that follow: the bed drawn, loops welded as the
    # ~90% case expects. A ladder whose result depends on the developer's own preferences is not
    # a gate.
    app["auto_close_sketch_loops"] = True
    with open(conf, "w") as f:
        json.dump(data, f, indent=1)
    for sub in ("user", "system", "presets", "vendor"):
        src = os.path.join(os.path.dirname(A.seed_from), sub)
        dst = os.path.join(datadir, sub)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)


def launch():
    global _proc
    datadir = A.datadir or os.path.join(tempfile.gettempdir(), "orcacad-uxcheck")
    seed_datadir(datadir)
    env = dict(os.environ)
    # WAYLAND_DISPLAY MUST GO, and GDK_BACKEND must say x11. GTK prefers Wayland whenever
    # WAYLAND_DISPLAY is set and ignores DISPLAY entirely, so a driver launched from a systemd
    # user unit (which inherits it) started the app on the DESKTOP session instead of the rig:
    # the process was alive, `xdotool search` on the rig display found nothing, and the window
    # was sitting on the user's own screen. Silent, and it drives a stray app at someone's face.
    env.pop("WAYLAND_DISPLAY", None)
    env.update(DISPLAY=DISP, GDK_BACKEND="x11", SNAPORCA_UXTRACE="1",
               LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe",
               # The rig's Xvfb has no input-method daemon, and a dead ibus context makes a
               # GtkEntry drop every character while the app looks fine. It cannot affect the
               # in-canvas field (ImGui needs no IM) but the app has other text fields, and a
               # display full of IBUS warnings has cost a whole misdiagnosis before.
               GTK_IM_MODULE="gtk-im-context-simple", XMODIFIERS="@im=none",
               # The key tracer is this driver's only positive signal that a keystroke reached
               # the Design panel at all. Without it "the field never opened" is indistinguishable
               # from "we never got into sketch mode", and the first run of this ladder reported
               # seven product failures that were really one driver racing a still-loading app.
               SNAPORCA_KEYTRACE="1",
               SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt",
               WEBKIT_DISABLE_DMABUF_RENDERER="1", WEBKIT_DISABLE_COMPOSITING_MODE="1")
    log = open(TRACE, "wb")
    _proc = subprocess.Popen([A.bin, "--datadir", datadir], env=env,
                             stdout=subprocess.DEVNULL, stderr=log)
    for _ in range(120):
        if win_id():
            return
        time.sleep(1)
    die("the app never showed a window on " + DISP)


def win_id():
    """The main window: the biggest top-level. Never by title — a saved project renames it."""
    best = None
    for w in sh(f"DISPLAY={DISP} xdotool search --class '.'").split():
        g = dict(l.split("=", 1) for l in
                 sh(f"DISPLAY={DISP} xdotool getwindowgeometry --shell {w}").strip().splitlines()
                 if "=" in l)
        if "WIDTH" not in g:
            continue
        a = int(g["WIDTH"]) * int(g["HEIGHT"])
        if a > 400 * 400 and (best is None or a > best[0]):
            best = (a, w, int(g["X"]), int(g["Y"]), int(g["WIDTH"]), int(g["HEIGHT"]))
    return best[1:] if best else None


_win = None


def win():
    global _win
    if _win is None:
        w = win_id()
        if w is None:
            die("no app window on " + DISP)
        sh(f"DISPLAY={DISP} xdotool windowactivate --sync {w[0]}")
        sh(f"DISPLAY={DISP} xdotool windowsize {w[0]} 1920 1080")
        sh(f"DISPLAY={DISP} xdotool windowmove {w[0]} 0 0")
        time.sleep(1.0)
        _win = (w[0], 0, 0, 1920, 1080)
    return _win


def click(px, py, pause=0.5, btn=1):
    _, X, Y, _, _ = win()
    xdo(f"mousemove {X+int(px)} {Y+int(py)} click --delay 120 {btn}")
    time.sleep(pause)


def dismiss_first_run():
    """Close whatever modal the first run puts up, by pressing its default button."""
    for _ in range(6):
        for w in sh(f"DISPLAY={DISP} xdotool search --name 'Plug-in|Wizard|OrcaSlicer'").split():
            n = sh(f"DISPLAY={DISP} xdotool getwindowname {w}").strip()
            if "Plug-in" in n or "Wizard" in n:
                sh(f"DISPLAY={DISP} xdotool windowactivate {w}")
                time.sleep(0.5)
                key("Escape", 0.5)
        time.sleep(0.5)


# ---------------------------------------------------------------- the trace

def trace_lines():
    try:
        with open(TRACE, "r", errors="replace") as f:
            return [l.strip() for l in f if l.startswith("[UX] ")]
    except OSError:
        return []


def trace_mark():
    return len(trace_lines())


def parse(line):
    m = re.match(r"\[UX\] (\w+) title=(.*?) (.*)$", line)
    if not m:
        return None
    ev, title, rest = m.group(1), m.group(2), m.group(3)
    kv = dict(re.findall(r"(\w+)=(\S*)", rest))
    return ev, title, kv


# ---------------------------------------------------------------- grading

def check(cond, what):
    global _fail, _checks
    _checks += 1
    if cond:
        print(f"    ok    {what}")
    else:
        print(f"    FAIL  {what}", file=sys.stderr)
        _fail += 1


def type_into_open_field(value, mark):
    """Type `value` into whatever field is open, WITHOUT clicking it first, and grade the pair.

    No click: the click is the workaround this ladder exists to refuse. If the field cannot take
    the keyboard on its own, `typed` will be the prefill and this fails — which is the report.
    """
    # POLL for the field. It opens from a CallAfter that runs after a re-solve, so on llvmpipe it
    # is simply not there yet when a fast driver looks — and "no field opened" is the same message
    # whether the product never opened one or the driver asked too early. Wait, then decide.
    opens = []
    deadline = time.time() + 8.0
    while time.time() < deadline:
        opens = [e for e in (parse(l) for l in trace_lines()[mark:]) if e and e[0] == "open"]
        if opens:
            break
        time.sleep(0.25)
    if not opens:
        check(False, f"a value field opened (nothing did; cannot type {value})")
        return mark
    title = opens[-1][1]
    prefill = opens[-1][2].get("prefill", "")
    m2 = trace_mark()
    typ(str(value), 0.4)
    key("Return", 0.9)
    after, commits, refused = [], [], []
    deadline = time.time() + 5.0
    while time.time() < deadline:
        after = [parse(l) for l in trace_lines()[m2:]]
        commits = [e for e in after if e and e[0] == "commit"]
        refused = [e for e in after if e and e[0] == "refused"]
        if commits or refused:
            break
        time.sleep(0.25)
    if refused and not commits:
        check(False, f"{title}: field REFUSED {value!r} (typed={refused[-1][2].get('typed')!r})")
        key("Escape", 0.5)
        return trace_mark()
    if not commits:
        check(False, f"{title}: typed {value} but nothing committed — the field took no keys")
        key("Escape", 0.5)
        return trace_mark()
    typed = commits[-1][2].get("typed", "")
    got = commits[-1][2].get("value", "")
    check(typed == str(value),
          f"{title}: field received what was typed (typed={typed!r} wanted={value!r}"
          f"{'  <-- it committed its PREFILL, so it never got the keyboard' if typed == prefill else ''})")
    check(abs(float(got or 0) - float(value)) < 1e-6,
          f"{title}: committed value is {got} (wanted {value})")
    check(str(value) != prefill, f"{title}: the test value differs from the prefill {prefill!r}")
    return trace_mark()


# ---------------------------------------------------------------- the ladder

def keytrace(after=0):
    """[KEYTRACE] lines from the app, which tell us what MODE a keystroke was seen in."""
    try:
        with open(TRACE, "r", errors="replace") as f:
            return [l.strip() for l in f if l.startswith("[KEYTRACE]")][after:]
    except OSError:
        return []


def in_sketch_mode():
    """ui_mode=1 on the most recent keystroke the panel saw."""
    for l in reversed(keytrace()):
        m = re.search(r"ui_mode=(\d+)", l)
        if m:
            return m.group(1) == "1"
    return False


def enter_sketch(timeout=120):
    """Design tab, then a sketch — waiting on EVIDENCE, never on a sleep.

    OrcaSlicer maps its main window well before it has finished loading presets, so a driver that
    counts three seconds and starts clicking sends every gesture into a window that is still busy.
    That is not a product failure but it reads exactly like one: no tool arms, no field opens, and
    the ladder reports the whole contract broken. So press the key and look for the app's own
    trace line saying it arrived, and keep trying until it does.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        click(132, 53)                   # Design tab
        time.sleep(2.0)
        xdo("mousemove 1200 600")
        key("shift+s", 1.5)              # start a sketch (offers the reference planes)
        if in_sketch_mode():
            time.sleep(1.5)
            return
        dismiss_first_run()
    die("never reached sketch mode — the app saw no keystroke in Design mode within "
        f"{timeout}s (trace {TRACE})")


# tool key, the clicks that draw it, and one distinct value per queued field. The values are
# deliberately nothing like the as-drawn size, so a committed prefill cannot coincide with them.
TOOLS = [
    ("L", "Line",      [(950, 500), (1350, 500)],              [61]),
    ("R", "Rectangle", [(950, 500), (1350, 700)],              [62, 43]),
    ("C", "Circle",    [(1150, 600), (1300, 600)],             [64]),
]


def rung_tool(k, name, clicks, values):
    print(f"  {name}")
    key("Escape", 0.6)                   # back to Select, whatever the last tool left armed
    key(k, 0.8)
    for (x, y) in clicks:
        click(x, y)
    mark = trace_mark()
    for v in values:
        mark = type_into_open_field(v, mark)


def rung_label_click():
    """The user's report: click an existing dimension label and type a new value into it."""
    print("  label click-to-edit")
    key("Escape", 0.6)                   # Select mode
    key("R", 0.8)
    click(900, 480)
    click(1300, 680)
    mark = trace_mark()
    for v in (55, 47):                   # walk the queued chain out of the way
        mark = type_into_open_field(v, mark)
    key("Escape", 0.8)                   # back to Select so a click picks rather than draws
    # The label sits on the dimension line above the rectangle's top edge. The chain just set the
    # width to 55, so the label reads "55.0 mm" near the midpoint of that edge.
    mark = trace_mark()
    click(1100, 455)
    reopened = False
    deadline = time.time() + 6.0
    while time.time() < deadline:
        if [e for e in (parse(l) for l in trace_lines()[mark:]) if e and e[0] == "open"]:
            reopened = True
            break
        time.sleep(0.25)
    if not reopened:
        check(False, "clicking a dimension label reopened its value field")
        return
    check(True, "clicking a dimension label reopened its value field")
    type_into_open_field(71, mark)


def main():
    if not A.attach:
        if not os.path.exists(A.bin):
            die(f"no binary at {A.bin}")
        open(TRACE, "w").close()
        launch()
        dismiss_first_run()
    win()
    print(f"click-edit ladder on {DISP}, trace {TRACE}")
    enter_sketch()
    for (k, name, clicks, values) in TOOLS:
        rung_tool(k, name, clicks, values)
    rung_label_click()
    print()
    if _fail:
        print(f"CLICK-EDIT LADDER FAILED — {_fail} of {_checks} checks", file=sys.stderr)
    else:
        print(f"CLICK-EDIT LADDER HELD — {_checks} checks")
    if _proc is not None and not A.keep:
        _proc.send_signal(signal.SIGTERM)
        try:
            _proc.wait(20)
        except subprocess.TimeoutExpired:
            _proc.kill()
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
