"""Cinopsis transcript sources - the v3 source seam.

A transcript SOURCE is an Agent-Reach Channel (scripts/reach/channels.py): it has
a name, an ordered list of backends, a tier, and a check() that really executes
what it needs (doctor reads that). Cinopsis adds one thing on top: rungs(), the
ordered (name, fn, door) tuples the get_transcript ladder walks. A rung function
takes a video id and returns (segments, lang) or (None, None); segments are
Cinopsis's [{"start": int, "text": str}].

Each Cinopsis instance picks its own ordered source list (R2):

    1. sources=  (CLI --sources a,b on every entry point; MCP `sources` param)
    2. allow_http_rungs=True          -> browser-panel,og-http  (the legacy flag)
    3. env CINOPSIS_TRANSCRIPT_SOURCES
    4. env CINOPSIS_ALLOW_HTTP_RUNGS=1 -> browser-panel,og-http
    5. settings.json transcript_sources (per instance)
    6. default: browser-panel  (Gavin's desk, unchanged from v2.9)

Recommended for a portable / Hazine install with no browser:
    CINOPSIS_TRANSCRIPT_SOURCES=gemini-url,local-pipeline,og-http

An unknown name raises ValueError naming the valid set - a typo must never fall
silently back to the default.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from reach.channels import ALL_CHANNELS, Channel
from reach.url import host_matches

ENV_SOURCES = "CINOPSIS_TRANSCRIPT_SOURCES"
ENV_ALLOW_HTTP = "CINOPSIS_ALLOW_HTTP_RUNGS"
DEFAULT_ORDER = ("browser-panel",)
LEGACY_HTTP_ORDER = ("browser-panel", "og-http")

Rung = tuple[str, Callable[[str], tuple], Optional[str]]


class SourceError(RuntimeError):
    """A source failed in a way the ladder should record against its door.

    Lifted Watch code reports failures as SystemExit (it is a CLI). SystemExit is
    a BaseException and would kill the whole ladder, so every source converts it
    to this at its boundary. The message keeps the upstream text, so 429 /
    quota markers still reach ratelimit.record_outcome and arm the right door.
    """


class TranscriptSource(Channel):
    """Base class for every Cinopsis transcript source."""

    kind: str = "caption"        # caption | asr | model - written to the provenance sidecar
    door: Optional[str] = None   # ratelimit door for this source's network calls
    network: bool = True         # False for loopback-only sources

    def can_handle(self, url: str) -> bool:
        return host_matches(url, "youtube.com", "youtu.be")

    def rungs(self) -> list[Rung]:
        raise NotImplementedError

    def live_probe(self, settings: dict) -> Optional[tuple[str, str]]:
        """At most ONE lightweight network request (doctor --live). None = nothing to probe."""
        return None


def _builtin_sources() -> list[TranscriptSource]:
    from sources.browser_panel import BrowserPanelSource
    from sources.og_http import OgHttpSource
    from sources.gemini_url import GeminiUrlSource
    from sources.local_pipeline import LocalPipelineSource
    from sources.claude_lane import ClaudeSource
    return [BrowserPanelSource(), OgHttpSource(), GeminiUrlSource(), LocalPipelineSource(), ClaudeSource()]


SOURCES: list[TranscriptSource] = _builtin_sources()
SOURCE_NAMES: tuple[str, ...] = tuple(s.name for s in SOURCES)


def register(channels: list[Channel] = ALL_CHANNELS) -> None:
    """Put every transcript source into Agent-Reach's channel registry (idempotent)."""
    present = {c.name for c in channels}
    for s in SOURCES:
        if s.name not in present:
            channels.append(s)


register()


def get_source(name: str) -> TranscriptSource:
    for s in SOURCES:
        if s.name == name:
            return s
    raise ValueError(f"unknown transcript source {name!r}; valid: {', '.join(SOURCE_NAMES)}")


def parse_order(value) -> tuple[str, ...]:
    """'a,b' or ['a','b'] -> ('a','b'), validated and de-duplicated in order."""
    if value is None:
        return ()
    items = value.split(",") if isinstance(value, str) else list(value)
    out: list[str] = []
    for raw in items:
        name = str(raw).strip().lower()
        if not name:
            continue
        get_source(name)
        if name not in out:
            out.append(name)
    return tuple(out)


def _truthy(v: Optional[str]) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def resolve_order(sources=None, allow_http_rungs=None, settings: Optional[dict] = None) -> tuple[tuple[str, ...], str]:
    """Return (ordered source names, where the order came from)."""
    explicit = parse_order(sources)
    if explicit:
        return explicit, "explicit"
    if allow_http_rungs:
        return LEGACY_HTTP_ORDER, "allow_http_rungs flag"
    env = parse_order(os.environ.get(ENV_SOURCES))
    if env:
        return env, f"env {ENV_SOURCES}"
    if _truthy(os.environ.get(ENV_ALLOW_HTTP)):
        return LEGACY_HTTP_ORDER, f"env {ENV_ALLOW_HTTP}"
    if settings is None:
        try:
            from app_settings import load_settings
            settings = load_settings()
        except Exception:
            settings = {}
    configured = parse_order((settings or {}).get("transcript_sources"))
    if configured:
        return configured, "settings transcript_sources"
    return DEFAULT_ORDER, "default"


def rungs_for(order) -> list[tuple[str, Callable, Optional[str], str]]:
    """Flatten an order into (rung name, fn, door, source name)."""
    out = []
    for name in order:
        for rung_name, fn, door in get_source(name).rungs():
            out.append((rung_name, fn, door, name))
    return out


def source_of_rung(rung_name: str) -> Optional[TranscriptSource]:
    for s in SOURCES:
        if any(r[0] == rung_name for r in s.rungs()):
            return s
    return None


def add_source_args(parser) -> None:
    """The one CLI switch every entry point carries (R2)."""
    parser.add_argument(
        "--sources", default=None,
        help=("Ordered transcript sources, comma separated: " + ",".join(SOURCE_NAMES)
              + f". Default: settings, then ${ENV_SOURCES}, then browser-panel."))
    parser.add_argument(
        "--allow-http-rungs", action="store_true",
        help="Shorthand for --sources browser-panel,og-http (same as CINOPSIS_ALLOW_HTTP_RUNGS=1).")
