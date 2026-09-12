"""Passive file-bus channel surface for Cinopsis (additive; the stdio MCP tools stay primary).

This joins Cinopsis to the shared Griot MCP channel architecture the same way brainstorm and
gavel do — a PASSIVE BUS mediated by the FILESYSTEM, not a live socket:

  OUT  option / status cards written as HTML to a per-session $SCREEN_DIR the cockpit renders
  IN   verb requests / events read as JSONL from $STATE_DIR/events

Nothing here depends on a live notification listener, so the SAME import runs unchanged in an
interactive terminal, in Cowork cloud, and under headless `claude -p`. It is a SECOND surface on
top of `mcp_server.py`'s stdio tools — it never replaces them and never writes to stdout, so the
MCP JSON-RPC channel cannot be corrupted. Every IO path is guarded; a bus failure is swallowed and
logged to stderr so the server can never crash because of it.

Reference floor: fragment-ai-scaffold create-fragment `templates/mcp/python/channel_bus.py`
and prism `scripts/digital-griot-mcp/digital-griot-mcp.ts` (`capabilities:{tools:{}}`,
`$STATE_DIR/events`, HTML cards to `$SCREEN_DIR`).

Layer LIVE-PUSH (experimental `claude/channel`) on top ONLY for interactive surfaces; never make
the bus's correctness depend on it.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_NAME = "cinopsis"

# The Cinopsis verbs, grouped as they are exposed on the channel surface. Each maps to the SAME
# underlying functions the stdio MCP tools wrap — no forked logic, one source of truth.
CINOPSIS_VERBS = {
    "fetch": {
        "label": "Fetch",
        "summary": "Surface recent / playlist videos and pull transcripts.",
        "tools": ["fetch_videos", "fetch_playlist", "fetch_transcripts", "get_transcript"],
    },
    "digest": {
        "label": "Digest",
        "summary": "Summarize videos into a digest / report / session.",
        "tools": ["digest_all", "generate_report", "build_session_from_analysis"],
    },
    "compare": {
        "label": "Compare",
        "summary": "Build a cross-video comparison session and dashboard.",
        "tools": ["compare_videos", "compare_server"],
    },
}


# ── dir resolution (STATE_DIR / SCREEN_DIR precedence, per channel-patterns.md) ───────────────

def _bus_root() -> Path:
    """Base dir under which per-session dirs live; override with $GRIOT_BUS_ROOT."""
    root = os.environ.get("GRIOT_BUS_ROOT")
    if root:
        return Path(root)
    return Path(tempfile.gettempdir()) / f"{PROJECT_NAME}-bus"


def _newest_session_dir(base: Path) -> Path | None:
    if not base.is_dir():
        return None
    dirs = [d for d in base.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def resolve_state_dir(explicit: str | None = None) -> Path:
    """STATE_DIR precedence: explicit arg -> $STATE_DIR env -> newest session dir -> fallback.
    The fallback is created so reads/writes never crash."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("STATE_DIR")
    if env:
        return Path(env)
    newest = _newest_session_dir(_bus_root())
    if newest:
        return newest
    fallback = _bus_root() / "default"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def resolve_screen_dir(explicit: str | None = None) -> Path:
    """SCREEN_DIR precedence mirrors STATE_DIR: explicit -> $SCREEN_DIR -> <state_dir>/screen."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("SCREEN_DIR")
    if env:
        return Path(env)
    return resolve_state_dir() / "screen"


# ── IN half — read events (JSONL), tolerant of a racing writer ────────────────────────────────

def read_events(state_dir: str | None = None, *, since: int = 0) -> list[dict]:
    """Read $STATE_DIR/events as JSONL, returning parsed records from line `since` on. A
    malformed / partially-written tail line is skipped, never raised. Returns [] when no events
    file exists yet."""
    try:
        path = resolve_state_dir(state_dir) / "events"
        if not path.is_file():
            return []
        out: list[dict] = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if i < since:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except Exception as e:  # never let a bus read crash the caller
        print(f"[{PROJECT_NAME}] channel_bus.read_events skipped: {e}", file=sys.stderr, flush=True)
        return []


def read_verb_requests(state_dir: str | None = None, *, since: int = 0) -> list[dict]:
    """Cinopsis-relevant events: records whose `verb` (or `content`) names one of CINOPSIS_VERBS.
    Lets a cockpit / router ask Cinopsis to run fetch/digest/compare over the bus."""
    hits = []
    for ev in read_events(state_dir, since=since):
        verb = str(ev.get("verb") or ev.get("meta", {}).get("verb") or "").lower()
        if verb in CINOPSIS_VERBS:
            hits.append(ev)
    return hits


# ── OUT half — write cards (temp-then-replace so a reader never sees a half-written card) ─────

def write_card(html: str, *, name: str = "card", screen_dir: str | None = None) -> Path | None:
    """Write an option / status card as HTML to $SCREEN_DIR the cockpit renders. Returns the path,
    or None if the write was swallowed (guarded — a bus write must never crash the server)."""
    try:
        sdir = resolve_screen_dir(screen_dir)
        sdir.mkdir(parents=True, exist_ok=True)
        dest = sdir / f"{name}.html"
        tmp = sdir / f".{name}.html.tmp"
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(dest)
        return dest
    except Exception as e:
        print(f"[{PROJECT_NAME}] channel_bus.write_card skipped: {e}", file=sys.stderr, flush=True)
        return None


def _surface_card_html() -> str:
    """A minimal status card advertising Cinopsis's verbs as bus surfaces. Griotwave-tinted, but
    self-contained (no external CSS) so it renders anywhere the cockpit drops it."""
    rows = "\n".join(
        f'    <li><b>{v["label"]}</b> — {v["summary"]}'
        f'<br><code>{" · ".join(v["tools"])}</code></li>'
        for v in CINOPSIS_VERBS.values()
    )
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<div style=\"font:13px/1.5 Inter,system-ui,sans-serif;color:#EDF2F4;"
        "background:#0B0C10;padding:16px;border-radius:12px;"
        "border:1px solid rgba(239,35,60,.28);max-width:520px\">"
        "<div style='font:600 11px/1 \"JetBrains Mono\",monospace;letter-spacing:.14em;"
        "text-transform:uppercase;color:#EF233C;margin-bottom:10px'>Cinopsis · channel surfaces</div>"
        f"<ul style='margin:0;padding-left:18px'>\n{rows}\n</ul>"
        "<div style='margin-top:10px;color:#8D99AE;font-size:11px'>Passive file bus — "
        "cards to $SCREEN_DIR, events from $STATE_DIR/events. The stdio MCP tools remain primary."
        "</div></div>"
    )


def advertise_surfaces(state_dir: str | None = None, screen_dir: str | None = None) -> dict:
    """Publish Cinopsis's verbs onto the shared channel bus. Writes:
      * `cinopsis-surfaces.json` — a machine manifest (tools:{} floor + verb registry) into STATE_DIR
      * `cinopsis-surfaces.html` — a human status card into SCREEN_DIR
    Fully guarded and headless-safe; returns the manifest (dict) it advertised. Any IO failure is
    swallowed so the MCP server can call this on startup without risk."""
    manifest = {
        "surface": PROJECT_NAME,
        "transport": "passive-bus",
        "capabilities": {"tools": {}},  # bus floor — the stdio tools carry the real capability
        "verbs": CINOPSIS_VERBS,
    }
    try:
        sdir = resolve_state_dir(state_dir)
        sdir.mkdir(parents=True, exist_ok=True)
        dest = sdir / "cinopsis-surfaces.json"
        tmp = sdir / ".cinopsis-surfaces.json.tmp"
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(dest)
    except Exception as e:
        print(f"[{PROJECT_NAME}] channel_bus.advertise_surfaces (state) skipped: {e}",
              file=sys.stderr, flush=True)
    write_card(_surface_card_html(), name="cinopsis-surfaces", screen_dir=screen_dir)
    return manifest


if __name__ == "__main__":  # tiny manual smoke — writes to a temp bus and reads back
    os.environ.setdefault("GRIOT_BUS_ROOT", str(Path(tempfile.gettempdir()) / "cinopsis-bus-smoke"))
    m = advertise_surfaces()
    print("advertised verbs:", list(m["verbs"]))
    print("state_dir:", resolve_state_dir())
    print("screen_dir:", resolve_screen_dir())
    print("events:", read_events())
