#!/usr/bin/env python3
"""Shared utilities for cinopsis scripts."""
import os
import shutil
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("CLAUDE_PLUGIN_DATA", Path(__file__).parent.parent / "data"))


def canonical_data_dir() -> Path:
    """Stable, persistent data dir the dashboard reads from.

    Matches mcp_launcher.plugin_data_dir() so Claude Code and Cowork share one
    session library. Override with CINOPSIS_DATA_DIR (used by tests / custom setups).
    """
    env = os.environ.get("CINOPSIS_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".claude" / "plugins" / "data" / "cinopsis-cinopsis"


def find_ytdlp():
    """Find yt-dlp, preferring the running interpreter's own venv binary.

    The server runs under the plugin venv, whose yt-dlp sits beside the
    interpreter (Scripts/ on Windows, bin/ on POSIX) and matches the version
    pinned in requirements.txt. Prefer it over a PATH hit or a stale per-user
    install (Cinopsis MCP-hang handoff, secondary fix: find_ytdlp ordering).
    """
    exe = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
    interp_dir = Path(sys.executable).parent
    for cand in (interp_dir / exe, interp_dir / "Scripts" / exe):
        if cand.exists():
            return str(cand)
    found = shutil.which("yt-dlp")
    if found:
        return found
    # Per-user pip install may be stale; last resort before the PATH fallback.
    ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
    user_scripts = Path.home() / "AppData" / "Roaming" / "Python" / ver / "Scripts" / "yt-dlp.exe"
    if user_scripts.exists():
        return str(user_scripts)
    return "yt-dlp"  # fallback, let it fail with a clear error


def get_env():
    """Return a sanitized copy of the environment for yt-dlp/ffmpeg subprocesses.

    Drops proxy vars Cowork's VM may inject (which can hang yt-dlp), per the
    Cinopsis MCP-hang handoff and claude-code #41432.
    """
    return {k: v for k, v in os.environ.items()
            if k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}


def find_ffmpeg():
    """Find an ffmpeg executable.

    Prefers the static binary bundled by imageio-ffmpeg (installed via pip, so it
    works with NO system install on any platform — including Cowork, where the
    plugin runs from a self-bootstrapped venv). Falls back to a system ffmpeg on
    PATH, then to the bare name so the caller fails with a clear error.
    """
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    return "ffmpeg"  # fallback, let it fail with a clear error
