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


COOKIE_FILENAME = "cookies.txt"


def cookie_targets():
    """Every path the cookie exporter should write the jar to, de-duplicated.

    Order: $CINOPSIS_COOKIES (when set) -> DATA_DIR/cookies.txt -> the canonical
    data dir's cookies.txt. Under the plugin CLAUDE_PLUGIN_DATA makes DATA_DIR and
    canonical_data_dir() the same directory, so this collapses to one path; in a bare
    dev run they diverge and BOTH need the jar (the readers check both -- see
    resolve_cookies). Returns a list[Path]; parent dirs are NOT created here.
    """
    candidates = []
    env = os.environ.get("CINOPSIS_COOKIES")
    if env:
        candidates.append(Path(env))
    candidates.append(DATA_DIR / COOKIE_FILENAME)
    candidates.append(canonical_data_dir() / COOKIE_FILENAME)
    seen, out = set(), []
    for cand in candidates:
        key = os.path.normcase(os.path.abspath(str(cand)))
        if key not in seen:
            seen.add(key)
            out.append(cand)
    return out


def resolve_cookies(cookies=None):
    """Resolve a cookies.txt path for yt-dlp so PRIVATE/unlisted videos are reachable.

    Precedence: explicit path -> $CINOPSIS_COOKIES -> DATA_DIR/cookies.txt ->
    canonical_data_dir()/cookies.txt (each of the last two only if it exists).
    Returns a path str, or None when no jar is available (public content still works).

    $CINOPSIS_COOKIES is returned WITHOUT an existence check on purpose: if the user
    named a jar explicitly, yt-dlp should fail loudly on a bad path rather than
    silently degrade to anonymous. The canonical rung is what keeps a bare dev run
    (DATA_DIR = <repo>/data) able to read a jar the exporter wrote to the plugin dir.

    A file-based cookies.txt (Netscape format) is used instead of yt-dlp's
    --cookies-from-browser: on Windows the latter fails with "Failed to decrypt with
    DPAPI" against Chrome App-Bound Encryption (yt-dlp #10927). An exported file
    sidesteps that. Written by scripts/export_yt_cookies.py.
    """
    if cookies:
        return str(cookies)
    env = os.environ.get("CINOPSIS_COOKIES")
    if env:
        return env
    for cand in (DATA_DIR / COOKIE_FILENAME, canonical_data_dir() / COOKIE_FILENAME):
        if cand.exists():
            return str(cand)
    return None


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
