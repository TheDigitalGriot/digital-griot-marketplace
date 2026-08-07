#!/usr/bin/env python3
"""
Griot · Flask art-preserving widget adapter  (GMCL-A1 — reusable template)

Any Griot Flask plugin that serves a bespoke viewer (Cinopsis today; Lucid, R3F Studio, and
Kora are coming in this same shape) can apply the Griot Widget Contract to its viewer
SERVER-SIDE, in Python, with NO JS-runtime import across the Python/JS gap:

  FRAME  — a :root token OVERRIDE that recolors the whole page to the plugin's design system,
           injected AFTER the viewer's own <style> so equal-specificity :root rules win by
           source order — every `var(--…)` the viewer already uses recolors cohesively with
           ZERO markup/JS changes. Plus a subtle ember grid, the plugin's logo chip, hairline.
  CTA    — one drive() control (the plugin's "capture"/"re-run" verb).
  HOOK   — an inline drive ladder mirroring packages/griot-widget/drive.cjs:
           Cowork sendPrompt → :52342 channel POST → clipboard, reached by the channel meta.

The machinery below is APP-AGNOSTIC. A plugin supplies a `GriotFlaskTheme` (its ember, token
map, logo mark, name, CTA). Cinopsis is the reference consumer: CINOPSIS_THEME. Idempotent —
a second frame_viewer() call is a no-op (guarded by GRIOT_MARKER).

    from griot_widget_adapter import frame_viewer            # Cinopsis default theme
    html = frame_viewer(viewer_html)
    # a future plugin:  frame_viewer(viewer_html, theme=LUCID_THEME)
"""
import json

GRIOT_MARKER = "griot-flask-frame"


def _rgb(hex_str):
    """'#EF233C' -> '239,35,60' (for rgba() interpolation in the frame chrome)."""
    h = hex_str.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


class GriotFlaskTheme:
    """A per-app design system for the shared Flask bind. The ONLY thing a new plugin swaps."""

    def __init__(self, app_name, ember, ember_deep, ember_soft, slate, void, tokens,
                 mark_svg, cta_label="Send to agent ↗", cta_payload=None):
        self.app_name = app_name
        self.ember = ember
        self.ember_deep = ember_deep
        self.ember_soft = ember_soft
        self.slate = slate
        self.void = void
        self.tokens = dict(tokens)
        self.mark_svg = mark_svg
        self.cta_label = cta_label
        self.cta_payload = cta_payload or {
            "verb": "capture",
            "source": app_name.lower(),
            "text": "Capture the current %s view and summarize the takeaways." % app_name,
        }


# ── generic machinery ───────────────────────────────────────────────────────────────────

def _tokens_css(theme):
    lines = "\n".join(f"  {k}: {v};" for k, v in theme.tokens.items())
    return (
        f"/* {GRIOT_MARKER}: {theme.app_name} design-system token override (wins by source order) */\n"
        ":root {\n"
        f"{lines}\n"
        f"  --griot-ember: {theme.ember};\n"
        f"  --griot-ember-deep: {theme.ember_deep};\n"
        f"  --griot-ember-soft: {theme.ember_soft};\n"
        f"  --griot-slate: {theme.slate};\n"
        f"  --griot-void: {theme.void};\n"
        "}"
    )


def _frame_css(theme):
    er = _rgb(theme.ember)   # ember as "r,g,b" for rgba() chrome accents
    vr = _rgb(theme.void)    # void ground for the glass chip
    return f"""
/* griotwave grid — subtle ember weave on the void (32px), radial-masked so it fades to edges */
body::before {{
  content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(var(--griot-ember) 1px, transparent 1px),
    linear-gradient(90deg, var(--griot-ember) 1px, transparent 1px);
  background-size: 32px 32px; opacity: 0.035;
  -webkit-mask-image: radial-gradient(120% 120% at 80% 0%, #000 0%, transparent 70%);
          mask-image: radial-gradient(120% 120% at 80% 0%, #000 0%, transparent 70%);
}}
/* ember hairline at the very top edge */
body::after {{
  content: ""; position: fixed; top: 0; left: 0; right: 0; height: 2px; z-index: 9998;
  pointer-events: none;
  background: linear-gradient(90deg, transparent, var(--griot-ember) 30%, var(--griot-ember-deep) 70%, transparent);
  opacity: 0.9;
}}
/* logo chip — the plugin mark in the ember, glassy, top-right, non-intrusive overlay */
.griot-frame-chip {{
  position: fixed; top: 10px; right: 14px; z-index: 9999;
  display: flex; align-items: center; gap: 8px;
  padding: 5px 11px 5px 9px; border-radius: 999px;
  background: rgba({vr},0.62); backdrop-filter: blur(40px) saturate(140%);
  -webkit-backdrop-filter: blur(40px) saturate(140%);
  border: 1px solid rgba({er},0.28);
  box-shadow: 0 0 22px -6px var(--griot-ember), inset 0 0 0 1px rgba(255,255,255,0.02);
  font: 600 11px/1 "JetBrains Mono", ui-monospace, monospace; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--griot-slate); user-select: none;
}}
.griot-frame-chip svg {{ width: 18px; height: 12px; color: var(--griot-ember);
  filter: drop-shadow(0 0 6px rgba({er},0.55)); }}
/* the ONE drive CTA — bottom-right ember pill */
.griot-drive-cta {{
  position: fixed; bottom: 16px; right: 16px; z-index: 9999;
  display: inline-flex; align-items: center; gap: 7px;
  padding: 9px 15px; border-radius: 11px; cursor: pointer;
  background: linear-gradient(180deg, var(--griot-ember), var(--griot-ember-deep));
  color: #fff; border: none;
  box-shadow: 0 8px 24px -8px var(--griot-ember-deep), inset 0 1px 0 rgba(255,255,255,0.22);
  font: 600 12.5px/1 "Inter", system-ui, sans-serif; letter-spacing: 0.01em;
  transition: transform .12s ease, box-shadow .12s ease;
}}
.griot-drive-cta:hover {{ transform: translateY(-1px);
  box-shadow: 0 12px 30px -8px var(--griot-ember-deep), inset 0 1px 0 rgba(255,255,255,0.28); }}
.griot-drive-cta:active {{ transform: translateY(0); background: var(--griot-ember-deep); }}
.griot-drive-cta .g-host {{ font: 600 10px/1 "JetBrains Mono", monospace; opacity: 0.8;
  padding: 2px 6px; border-radius: 6px; background: rgba(0,0,0,0.22); }}
"""


def _drive_js(channel_port, theme):
    # Inline mirror of packages/griot-widget/drive.cjs — the same fallback ladder, no import.
    payload_json = json.dumps(theme.cta_payload)
    return f"""
(function () {{
  function meta(n) {{ var e = document.querySelector('meta[name="' + n + '"]');
    return e ? e.getAttribute('content') : null; }}
  var CH = meta('brainstorm-channel-port') || '{channel_port}';
  function detectRung() {{
    if (typeof window.__MCP_APP__ !== 'undefined') return 'mcp-app';
    if (typeof window.sendPrompt === 'function') return 'cowork';
    if (CH) return 'channel';
    return 'clipboard';
  }}
  function drive(payload) {{
    var text = (typeof payload === 'string') ? payload : (payload.text || payload.prompt || '');
    var rung = detectRung();
    try {{
      if (rung === 'mcp-app') {{ (window.parent || window).postMessage({{ type: 'griot/drive', payload: payload }}, '*'); }}
      else if (rung === 'cowork') {{ window.sendPrompt(text); }}
      else if (rung === 'channel') {{
        fetch('http://127.0.0.1:' + CH + '/channel', {{ method: 'POST', keepalive: true,
          headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(payload) }}).catch(function () {{}});
      }} else if (navigator.clipboard) {{ navigator.clipboard.writeText(text); }}
    }} catch (e) {{}}
    return rung;
  }}
  window.griotDrive = drive;
  var host = document.getElementById('griot-drive-host');
  function label() {{ if (host) host.textContent = detectRung(); }}
  label(); setInterval(label, 2000);
  var cta = document.getElementById('griot-drive-cta');
  if (cta) cta.addEventListener('click', function () {{ drive({payload_json}); }});
}})();
"""


def _chrome_markup(theme):
    return (
        f'<div class="griot-frame-chip">{theme.mark_svg}<span>{theme.app_name}</span></div>\n'
        '<button type="button" id="griot-drive-cta" class="griot-drive-cta">'
        f'{theme.cta_label} <span class="g-host" id="griot-drive-host">…</span></button>'
    )


def frame_viewer(html, theme=None, session_id=None, channel_port="52342"):
    """Apply the art-preserving griotwave bind to a Flask viewer's HTML. Idempotent.
    theme defaults to CINOPSIS_THEME; pass another GriotFlaskTheme to reuse for a new plugin."""
    if html is None:
        return html
    if GRIOT_MARKER in html:  # already framed — no double-inject
        return html
    theme = theme or CINOPSIS_THEME

    sid = session_id or theme.app_name.lower()
    head_block = (
        f'<meta name="brainstorm-channel-port" content="{channel_port}">\n'
        f'<meta name="brainstorm-session-id" content="{sid}">\n'
        f"<style>\n{_tokens_css(theme)}\n{_frame_css(theme)}\n</style>"
    )
    body_block = _chrome_markup(theme) + "\n<script>" + _drive_js(channel_port, theme) + "</script>"

    if "</head>" in html:
        html = html.replace("</head>", head_block + "\n</head>", 1)
    else:
        html = head_block + "\n" + html
    if "</body>" in html:
        idx = html.rfind("</body>")  # before the LAST </body> (gavel/brainstorm server guard)
        html = html[:idx] + body_block + "\n" + html[idx:]
    else:
        html = html + "\n" + body_block
    return html


# ── Cinopsis theme — the reference consumer (locked YT-Red griotwave direction) ───────────
# Ember is a CUSTOM-REGISTERED promotion of red out of Griotwave's reserved danger channel,
# because Cinopsis *is* a video/YouTube tool (per .prism/shared/brand/00-START-HERE.md).
CINOPSIS_EMBER = "#EF233C"
CINOPSIS_EMBER_DEEP = "#D90429"
CINOPSIS_EMBER_SOFT = "#FCA5A5"
CINOPSIS_SLATE = "#8D99AE"
CINOPSIS_INK = "#2B2D42"
CINOPSIS_LIGHT = "#EDF2F4"
CINOPSIS_VOID = "#0B0C10"

# Full replacement of the viewer's :root. The four data-encoding hues stay DISTINCT (they
# separate videos) but are re-tuned into one cohesive family that sits with the ember instead
# of the old generic purple/blue set (per Gavin: "the purple and old colors are outdated").
CINOPSIS_TOKENS = {
    "--bg": CINOPSIS_VOID,
    "--panel-bg": "#0D0E14",
    "--card-bg": "#16171F",
    "--entry-bg": CINOPSIS_VOID,
    "--border-panel": "#1C1F2B",
    "--border-card": CINOPSIS_INK,
    "--text-primary": CINOPSIS_LIGHT,
    "--text-secondary": CINOPSIS_SLATE,
    "--text-muted": "#5B6472",
    "--brand-purple": CINOPSIS_EMBER,        # brand accent → YT-Red ember
    "--active-purple": CINOPSIS_EMBER_DEEP,  # active/pressed → deep red
    "--blue": "#4EA1FF",
    "--green": "#2DD4BF",
    "--yellow": "#F5A524",
    "--pink": "#FF6B7A",                      # Cinopsis soft-red (already in the palette)
}

# The real traced Cinopsis mark (.prism/shared/brand/assets/cinopsis-mark.svg).
# fill="currentColor" → it inherits the ember wherever it is placed.
CINOPSIS_MARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 633 412" fill="currentColor" '
    'aria-hidden="true"><path fill-rule="evenodd" d="M91.84 406.46 C70.39 403.12 52.09 '
    '393.90 35.91 378.30 C21.93 364.83 12.63 348.93 7.18 329.21 L4.50 319.50 L4.51 206.00 '
    'L4.51 92.50 L7.22 82.65 C18.79 40.65 51.18 11.33 93.00 5.01 C98.37 4.20 136.27 3.97 '
    '226.50 4.19 L352.50 4.50 L359.87 7.23 C371.76 11.64 379.89 16.76 388.00 24.96 C396.81 '
    '33.88 401.09 40.73 405.32 52.74 L408.41 61.50 L409.02 103.50 C409.61 143.61 409.74 '
    '145.74 411.82 150.78 C414.75 157.90 416.68 160.74 421.90 165.66 C430.65 173.92 442.64 '
    '177.75 453.98 175.93 C462.31 174.58 462.21 174.63 485.06 160.97 C503.61 149.87 550.34 '
    '122.50 567.29 112.80 C575.79 107.94 578.07 107.07 585.31 105.88 C601.22 103.29 617.95 '
    '112.09 625.53 127.05 C629.58 135.06 630.05 145.00 629.56 212.50 C629.07 279.86 629.28 '
    '277.63 622.51 287.51 C615.34 297.99 603.80 304.02 591.00 303.97 C580.62 303.92 576.34 '
    '302.19 553.37 288.80 C524.02 271.69 490.25 252.16 484.15 248.76 C481.21 247.13 474.31 '
    '243.13 468.82 239.89 C463.33 236.65 458.64 234.00 458.40 234.00 C458.16 234.00 456.06 '
    '232.80 453.73 231.32 C448.87 228.24 402.84 201.58 388.00 193.24 C383.04 190.46 362.38 '
    '178.48 360.00 177.02 C359.18 176.51 352.65 172.74 345.50 168.64 C338.35 164.55 324.62 '
    '156.61 315.00 151.01 C270.81 125.29 243.45 109.67 240.21 108.32 C230.70 104.34 218.30 '
    '104.83 208.61 109.58 C201.58 113.02 193.75 121.17 190.20 128.75 L187.50 134.50 L187.50 '
    '205.00 L187.50 275.50 L190.18 281.22 C193.88 289.11 200.65 296.02 208.70 300.10 C215.07 '
    '303.33 215.93 303.50 225.95 303.49 C238.75 303.48 231.57 306.94 294.50 270.51 C330.54 '
    '249.65 342.62 242.93 346.00 241.88 C347.93 241.29 353.37 240.57 358.10 240.28 C372.46 '
    '239.42 384.23 243.99 394.48 254.38 C400.87 260.86 404.35 266.89 406.60 275.34 C408.33 '
    '281.84 408.59 342.03 406.92 350.20 C401.03 379.07 378.87 401.10 350.23 406.58 C339.59 '
    '408.62 104.97 408.50 91.84 406.46 Z"/></svg>'
)

CINOPSIS_THEME = GriotFlaskTheme(
    app_name="Cinopsis",
    ember=CINOPSIS_EMBER, ember_deep=CINOPSIS_EMBER_DEEP, ember_soft=CINOPSIS_EMBER_SOFT,
    slate=CINOPSIS_SLATE, void=CINOPSIS_VOID, tokens=CINOPSIS_TOKENS, mark_svg=CINOPSIS_MARK_SVG,
    cta_payload={
        "verb": "capture", "source": "cinopsis",
        "text": "Capture the current Cinopsis comparison view and summarize the cross-video takeaways.",
    },
)


if __name__ == "__main__":  # tiny manual smoke
    demo = "<html><head><style>:root{--bg:#0f1117;}</style></head><body><div id='app'>graph</div></body></html>"
    out = frame_viewer(demo)
    print("framed:", GRIOT_MARKER in out, "| ember:", CINOPSIS_EMBER in out,
          "| graph intact:", "id='app'" in out, "| idempotent:", frame_viewer(out) == out)
