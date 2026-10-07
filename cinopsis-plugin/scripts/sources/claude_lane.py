"""claude - the Claude lane, kept for testing behind its flag (R2).

This lane wraps Cinopsis's chat-provider seam (scripts/providers: claude_sub /
claude_key / local). A chat model cannot watch the video, so this source only
RESTRUCTURES material already on disk - today the description written by the
local-pipeline description writer (data/description_<id>.txt), which for many
tutorials carries timestamped chapter lines. It returns nothing when there is no
material, and its kind is "model", so the provenance sidecar never lets its text
pass as a caption track. Select it explicitly: --sources claude.
"""
from __future__ import annotations

from pathlib import Path

from sources import SourceError, TranscriptSource

DOOR_CLAUDE = "claude"
QUESTION = (
    "From the material above ONLY, list every timestamped line it contains as '[MM:SS] text', "
    "one per line, in time order. Do not invent, expand, or paraphrase. "
    "If the material has no timestamped lines, reply with exactly NONE."
)


def _material(video_id: str) -> str:
    from _utils import DATA_DIR
    p = Path(DATA_DIR) / f"description_{video_id}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def fetch_claude(video_id: str):
    from app_settings import load_settings
    from providers import chat_stream
    from sources.gemini_url import parse_timestamped
    material = _material(video_id)
    if not material.strip():
        return None, None
    answer = "".join(chat_stream(load_settings(), material, QUESTION))
    if "[chat error]" in answer:
        raise SourceError(answer)
    if answer.strip().upper() == "NONE":
        return None, None
    segs = parse_timestamped(answer)
    return (segs or None), ("auto" if segs else None)


class ClaudeSource(TranscriptSource):
    name = "claude"
    description = "Claude lane (testing): restructures on-disk description material"
    backends = ["provider-seam"]
    tier = 1
    kind = "model"
    door = DOOR_CLAUDE

    def rungs(self):
        return [("claude", fetch_claude, DOOR_CLAUDE)]

    def check(self, config=None):
        try:
            from app_settings import load_settings
            provider = load_settings().get("provider", "claude_sub")
        except Exception as exc:
            self.active_backend = None
            return "error", f"settings unreadable: {exc}"
        self.active_backend = provider
        return "ok", f"provider {provider}; testing lane, explicit --sources claude only"
