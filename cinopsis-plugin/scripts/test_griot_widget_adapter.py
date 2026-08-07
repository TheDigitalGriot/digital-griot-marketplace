#!/usr/bin/env python3
"""
GMCL-A1 · Cinopsis art-preserving adapter acceptance (automated).
Proves the framed compare-graph carries: the griotwave :root token block + Cinopsis ember,
the outdated palette remapped (purple → ember) so the cascade recolors cohesively, one
drive-bound CTA, the cinopsis-mark logo, the channel meta — and that the bespoke graph
markup/JS is INTACT + the bind is idempotent. Also runs against the real viewer.html.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from griot_widget_adapter import (  # noqa: E402
    frame_viewer, GRIOT_MARKER, CINOPSIS_EMBER, CINOPSIS_EMBER_DEEP, CINOPSIS_TOKENS,
)

n = 0
def ok(m):
    global n; n += 1; print("  ok ·", m)

# A mini-viewer mirroring the real one: its own :root (outdated purple) + #app + a var() use.
VIEWER = (
    "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
    "<style>:root{--bg:#0f1117;--brand-purple:#a78bfa;--active-purple:#7c3aed;--blue:#60a5fa;}"
    ".node{color:var(--brand-purple);border:1px solid var(--blue);}</style></head>"
    "<body><div id='app'><svg class='compare-graph'><g class='node'>video</g></svg></div>"
    "<script>const G='graph-logic';</script></body></html>"
)
out = frame_viewer(VIEWER)

# 1 · griotwave :root token block + Cinopsis ember present
assert GRIOT_MARKER in out and CINOPSIS_EMBER in out
ok("framed output carries the griotwave :root token block + Cinopsis ember (#EF233C)")

# 2 · the outdated palette is remapped: purple → ember family (cascade recolors cohesively)
assert f"--brand-purple: {CINOPSIS_EMBER};" in out
assert f"--active-purple: {CINOPSIS_EMBER_DEEP};" in out
ok("outdated purple tokens remapped to the Cinopsis ember family (brand→#EF233C, active→#D90429)")

# 3 · the override wins by SOURCE ORDER — it lands after the viewer's own :root
assert out.index("--brand-purple:#a78bfa") < out.index(GRIOT_MARKER)
ok("override injected AFTER the viewer's own :root → equal-specificity cascade win")

# 4 · one drive-bound CTA + the full inline ladder (cowork → :52342 → clipboard)
assert 'id="griot-drive-cta"' in out and "window.griotDrive" in out
assert "sendPrompt" in out and "/channel" in out and "clipboard" in out
ok("one drive() CTA present, wired to the cowork→:52342→clipboard ladder")

# 5 · the real cinopsis-mark logo + channel meta
assert 'viewBox="0 0 633 412"' in out
assert 'brainstorm-channel-port' in out and 'content="52342"' in out
ok("cinopsis-mark logo chip + :52342 channel meta injected")

# 6 · GRAPH INTACT — bespoke markup + JS untouched
assert "<div id='app'>" in out and "class='compare-graph'" in out
assert "var(--brand-purple)" in out and "var(--blue)" in out  # graph still draws via vars
assert "const G='graph-logic'" in out
ok("bespoke compare-graph markup + JS untouched (art-preserving)")

# 7 · idempotent — re-framing is a no-op
assert frame_viewer(out) == out
ok("idempotent: a second frame_viewer() call changes nothing")

# 8 · every declared token override is emitted
for k, v in CINOPSIS_TOKENS.items():
    assert f"{k}: {v};" in out, f"missing token {k}"
ok(f"all {len(CINOPSIS_TOKENS)} design-system tokens emitted in the override")

# 9 · REAL viewer.html — frame the actual 89KB art
real = Path(__file__).parent.parent / "viewer" / "viewer.html"
if real.exists():
    src = real.read_text(encoding="utf-8")
    framed = frame_viewer(src)
    assert GRIOT_MARKER in framed and CINOPSIS_EMBER in framed
    assert '<div id="app">' in framed                      # real graph mount preserved
    assert framed.count("</body>") == src.count("</body>")  # no stray body tags
    assert "--brand-purple: #a78bfa" in framed              # viewer's own :root kept…
    assert framed.index("--brand-purple: #a78bfa") < framed.index(GRIOT_MARKER)  # …override wins
    assert frame_viewer(framed) == framed                   # idempotent on the real file
    ok("real viewer.html frames cleanly — graph mount intact, override wins, idempotent")
else:
    print("  -- real viewer.html not found at", real, "(skipped real-file check)")

# 10 · GENERIC — the template is reusable: a non-Cinopsis theme lands its OWN ember/tokens,
#      with no Cinopsis bleed-through. This is the "future Flask plugins" contract (Lucid/R3F/Kora).
from griot_widget_adapter import GriotFlaskTheme  # noqa: E402
LUCID = GriotFlaskTheme(
    app_name="Lucid", ember="#7C3AED", ember_deep="#5B21B6", ember_soft="#C4B5FD",
    slate="#8D99AE", void="#0B0C10",
    tokens={"--bg": "#0B0C10", "--brand-purple": "#7C3AED"},
    mark_svg="<svg viewBox='0 0 10 10'><path d='M0 0'/></svg>",
)
lout = frame_viewer("<html><head></head><body><div id='app'>g</div></body></html>", theme=LUCID)
assert "#7C3AED" in lout and ">Lucid<" in lout
assert CINOPSIS_EMBER not in lout                 # no Cinopsis bleed-through
assert "--brand-purple: #7C3AED;" in lout         # Lucid's own token override emitted
assert "Capture the current Lucid view" in lout   # theme-derived CTA payload
ok("generic template reusable — a non-Cinopsis theme lands its own ember/tokens/CTA, no bleed")

print(f"\nALL {n} ASSERTIONS PASSED")
