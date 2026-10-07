"""gemini-url - Google watches the video by URL (the Watch Gemini engine).

Cinopsis hands the YouTube URL to Gemini's Interactions API with agentic video
processing (media.gemini.ask, lifted from claude-video). Google fetches the
video, so nothing touches YouTube from this machine's IP and no browser is
involved - this is the portable source for a Hazine-style install.

Key lookup (never printed, never written by Cinopsis): settings.json
gemini_api_key, then GEMINI_API_KEY in the environment, then Watch's own
~/.config/watch/.env and a project .env (media.config.load_gemini_key).

Gemini returns MODEL-DERIVED text, not a caption track, so its kind is "model"
and the provenance sidecar says so.
"""
from __future__ import annotations

import re
import sys
from typing import Optional

from sources import SourceError, TranscriptSource

DOOR_GEMINI = "gemini"
TRANSCRIPT_QUESTION = (
    "Transcribe everything that is spoken in this video, verbatim and in chronological order. "
    "Put each utterance on its own line, starting with its timestamp in square brackets as "
    "[MM:SS] or [H:MM:SS]. Do not summarise, translate, or add commentary or headings."
)
_LINE = re.compile(r"^\s*[*-]?\s*\[?((?:\d{1,2}:)?\d{1,2}:\d{2})(?:[.,]\d+)?\]?\s*[-–—:]?\s*(.+?)\s*$")


def gemini_key(settings: Optional[dict] = None) -> Optional[str]:
    from media import config as watch_config
    settings = settings if settings is not None else _settings()
    key = (settings.get("gemini_api_key") or "").strip()
    if key:
        return key
    try:
        return watch_config.load_gemini_key()
    except watch_config.ConfigError:
        return None


def gemini_model(settings: Optional[dict] = None) -> tuple[str, float]:
    from media import config as watch_config
    settings = settings if settings is not None else _settings()
    try:
        cfg = watch_config.get_config()
        model, timeout = cfg["gemini_model"], cfg["gemini_timeout"]
    except watch_config.ConfigError:
        model, timeout = watch_config.DEFAULT_GEMINI_MODEL, 600.0
    return (settings.get("gemini_model") or model), timeout


def _settings() -> dict:
    try:
        from app_settings import load_settings
        return load_settings()
    except Exception:
        return {}


def parse_timestamped(text: str) -> list[dict]:
    """'[MM:SS] words' lines -> Cinopsis segments, in time order. Untimed lines join the previous one."""
    from media.frames import parse_time
    segs: list[dict] = []
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if m:
            try:
                start = parse_time(m.group(1))
            except SystemExit:
                start = None
            if start is not None:
                segs.append({"start": int(start), "text": m.group(2).strip()})
                continue
        if segs and line.strip() and not line.lstrip().startswith("#"):
            segs[-1]["text"] = f"{segs[-1]['text']} {line.strip()}"
    segs.sort(key=lambda s: s["start"])
    return [s for s in segs if s["text"]]


def fetch_gemini_url(video_id: str):
    """Rung: (segments, 'auto') or (None, None) when no key is configured."""
    from media import gemini
    settings = _settings()
    key = gemini_key(settings)
    if not key:
        print("[gemini-url] no Gemini key (settings gemini_api_key or GEMINI_API_KEY); skipping",
              file=sys.stderr)
        return None, None
    model, timeout = gemini_model(settings)
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        result = gemini.ask({"uri": url}, TRANSCRIPT_QUESTION, model=model, key=key, timeout=timeout)
    except SystemExit as exc:  # lifted CLI code reports failure as SystemExit
        raise SourceError(str(exc)) from None
    segs = parse_timestamped(result["text"])
    if not segs:
        raise SourceError(f"Gemini answered without timestamped lines ({len(result['text'])} chars)")
    return segs, "auto"


class GeminiUrlSource(TranscriptSource):
    name = "gemini-url"
    description = "Gemini watches the URL (Google fetches; no browser, off this IP)"
    backends = ["gemini-interactions"]
    tier = 1
    kind = "model"
    door = DOOR_GEMINI

    def rungs(self):
        return [("gemini-url", fetch_gemini_url, DOOR_GEMINI)]

    def check(self, config=None):
        settings = _settings()
        model, _ = gemini_model(settings)
        if gemini_key(settings):
            self.active_backend = "gemini-interactions"
            return "ok", f"Gemini key present; model {model}"
        self.active_backend = None
        return "off", "no Gemini key - set GEMINI_API_KEY or settings gemini_api_key (https://aistudio.google.com/apikey)"

    def live_probe(self, settings):
        """ONE GET of the model resource, behind the gemini door. Never a video request."""
        from media import gemini
        import ratelimit
        key = gemini_key(settings)
        if not key:
            return "off", "no key - nothing probed"
        model, _ = gemini_model(settings)
        try:
            ratelimit.check_gate("doctor", door=DOOR_GEMINI)
        except ratelimit.RateLimited as exc:
            return "warn", f"gemini door cooling - not probed ({exc})"
        try:
            gemini._call("GET", f"{gemini.API}/v1beta/models/{model}", key, timeout=15)
        except SystemExit as exc:
            return "error", str(exc)
        return "ok", f"model {model} reachable"
