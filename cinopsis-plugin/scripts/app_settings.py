#!/usr/bin/env python3
"""Read/write the user-selectable AI provider settings.

Persisted to ``${CLAUDE_PLUGIN_DATA}/settings.json`` so the choice survives
plugin updates and is shared by the MCP server, the viewer, and the chat route.
"""
import json
import os
from pathlib import Path

DEFAULTS = {
    "provider": "claude_sub",                  # claude_sub | claude_key | local
    "model": "claude-sonnet-5-5",               # used by claude_key (bumped 2026-09-30; was pinned 2 versions stale at claude-sonnet-4-6)
    "anthropic_api_key": "",                   # fallback key (Q4 -> B)
    "local_base_url": "http://localhost:11434/v1",
    "local_model": "",
    "local_api_key": "",
    # v3 transcript source seam (per instance; see scripts/sources). Empty = the
    # CINOPSIS_TRANSCRIPT_SOURCES env var, then the default order.
    "transcript_sources": "",                  # e.g. "gemini-url,local-pipeline,og-http"
    "gemini_api_key": "",                      # gemini-url source; GEMINI_API_KEY env also works
    "gemini_model": "",                        # empty = Watch default (media.config.DEFAULT_GEMINI_MODEL)
    "sub_lang": "auto",                        # local-pipeline caption language (Watch select_caption)
}

SECRET_KEYS = {"anthropic_api_key", "local_api_key", "gemini_api_key"}


def _settings_path() -> Path:
    data = Path(os.environ.get("CLAUDE_PLUGIN_DATA", Path(__file__).resolve().parent.parent / "data"))
    return data / "settings.json"


def load_settings() -> dict:
    """Full settings (incl. secrets) for server-side use.

    Precedence per field: the in-viewer Settings file wins, then plugin
    ``userConfig`` (exported as CLAUDE_PLUGIN_OPTION_* env vars), then the
    plain ANTHROPIC_API_KEY env var, then DEFAULTS.
    """
    file_data = {}
    p = _settings_path()
    if p.exists():
        try:
            file_data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            file_data = {}

    env = os.environ

    def pick(key, env_name, default):
        return file_data.get(key) or env.get(env_name) or default

    data = dict(DEFAULTS)
    data["provider"] = file_data.get("provider") or DEFAULTS["provider"]
    data["model"] = file_data.get("model") or DEFAULTS["model"]
    data["anthropic_api_key"] = (
        file_data.get("anthropic_api_key")
        or env.get("CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY")
        or env.get("ANTHROPIC_API_KEY")
        or ""
    )
    data["local_base_url"] = pick("local_base_url", "CLAUDE_PLUGIN_OPTION_LOCAL_BASE_URL", DEFAULTS["local_base_url"])
    data["local_model"] = pick("local_model", "CLAUDE_PLUGIN_OPTION_LOCAL_MODEL", "")
    data["local_api_key"] = file_data.get("local_api_key") or env.get("CLAUDE_PLUGIN_OPTION_LOCAL_API_KEY") or ""
    data["transcript_sources"] = file_data.get("transcript_sources") or ""
    data["gemini_api_key"] = file_data.get("gemini_api_key") or env.get("GEMINI_API_KEY") or ""
    data["gemini_model"] = pick("gemini_model", "CINOPSIS_GEMINI_MODEL", "")
    data["sub_lang"] = file_data.get("sub_lang") or DEFAULTS["sub_lang"]
    return data


def save_settings(updates: dict) -> dict:
    """Persist only known keys; returns the public (secret-masked) view."""
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if p.exists():
        try:
            current = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            current = {}
    for k, v in (updates or {}).items():
        if k in DEFAULTS:
            current[k] = v
    p.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return public_settings()


def public_settings() -> dict:
    """Settings safe to send to the browser — secrets reduced to '<key>_set' booleans."""
    s = load_settings()
    out = {}
    for k, v in s.items():
        if k in SECRET_KEYS:
            out[k + "_set"] = bool(v)
        else:
            out[k] = v
    return out
