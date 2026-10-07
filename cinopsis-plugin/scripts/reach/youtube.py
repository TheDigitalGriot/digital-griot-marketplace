# Cinopsis reach layer - raw lift of Agent-Reach (channel / probe / doctor model) at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/channels/youtube.py:1-141
# -*- coding: utf-8 -*-
"""YouTube — check if yt-dlp is available with JS runtime."""

import re
import shutil

from reach.probe import probe_command  # seam: package import
from _utils import find_ytdlp  # seam: Cinopsis yt-dlp resolver
from reach.paths import (  # seam: package import
    PrivatePathError,
    get_ytdlp_config_path,
    read_small_text_no_follow,
    render_ytdlp_fix_command,
)

from reach.channels import Channel  # seam: package import

_JS_RUNTIMES_SUPPORTED_FROM = (2025, 11, 12)
_YTDLP_UPGRADE_COMMAND = 'python -m pip install -U "yt-dlp[default]"'


def _parse_ytdlp_version(version: str):
    """Return a comparable stable yt-dlp release tuple, if recognised."""
    match = re.fullmatch(r"\s*(\d{4})\.(\d{1,2})\.(\d{1,2})\s*", version)
    return tuple(map(int, match.groups())) if match else None


def _has_js_runtime_config(config_path) -> bool:
    """Return whether yt-dlp config explicitly enables a JS runtime."""
    try:
        payload = read_small_text_no_follow(
            config_path,
            max_bytes=1024 * 1024,
        )
        return payload is not None and "--js-runtimes" in payload
    except (OSError, UnicodeError, PrivatePathError):
        return False


class YouTubeChannel(Channel):
    name = "youtube"
    description = "YouTube video + captions (yt-dlp)"  # seam: English UI
    backends = ["yt-dlp"]
    tier = 0

    def can_handle(self, url: str) -> bool:
        from reach.url import host_matches  # seam: package import

        return host_matches(url, "youtube.com", "youtu.be")

    def check(self, config=None):
        # 真跑 yt-dlp --version 探活，区分未装 / venv 断链 / 跑不动
        probe = probe_command("yt-dlp" if shutil.which("yt-dlp") else find_ytdlp(), ["--version"], timeout=10, package="yt-dlp")  # seam: Cinopsis yt-dlp resolver (venv binary when not on PATH)
        if probe.status == "missing":
            self.active_backend = None
            return "off", f"yt-dlp is not installed. Install: {_YTDLP_UPGRADE_COMMAND}"  # seam: English UI
        if probe.status == "broken":
            self.active_backend = None
            return "error", (
                "yt-dlp is installed but cannot run. Reinstall (with JS support):\n"  # seam: English UI
                f"  {_YTDLP_UPGRADE_COMMAND}\n{probe.hint}"
            )
        if not probe.ok:  # timeout / error：装了但跑不动
            self.active_backend = None
            detail = probe.hint or probe.output or probe.status
            return "error", f"yt-dlp does not run cleanly: {detail}"  # seam: English UI
        # yt-dlp 本体是活的；后面的 JS runtime/转写检查只影响 ok/warn，不影响后端归属
        self.active_backend = "yt-dlp"
        # Check JS runtime
        has_js = shutil.which("deno") or shutil.which("node")
        if not has_js:
            return "warn", (
                "yt-dlp is installed but has no JS runtime (YouTube needs one).\n"  # seam: English UI
                "  Install Node.js or deno, then rerun: python scripts/doctor.py"  # seam: English UI
            )
        # Check yt-dlp config for --js-runtimes
        # Deno works out of the box; Node.js requires explicit config
        has_deno = shutil.which("deno")
        if not has_deno:
            ytdlp_config = get_ytdlp_config_path()
            if not _has_js_runtime_config(ytdlp_config):
                version = _parse_ytdlp_version(probe.output)
                if version is None:
                    return "warn", (
                        "Cannot tell whether this yt-dlp version supports the JS runtime setting. "  # seam: English UI
                        "Upgrade it and rerun doctor:\n"  # seam: English UI
                        f"  {_YTDLP_UPGRADE_COMMAND}"
                    )
                if version < _JS_RUNTIMES_SUPPORTED_FROM:
                    return "warn", (
                        "yt-dlp is too old for the JS runtime setting. Upgrade it and rerun doctor:\n"  # seam: English UI
                        f"  {_YTDLP_UPGRADE_COMMAND}"
                    )
                return "warn", (
                    f"yt-dlp is installed but no JS runtime is configured. Run:\n  {render_ytdlp_fix_command()}"  # seam: English UI
                )
        # Surface transcription readiness so `doctor` reports it.
        msg = "video info and captions available"  # seam: English UI
        if config is not None:
            providers = []
            if config.is_configured("groq_whisper"):
                providers.append("groq")
            if config.is_configured("openai_whisper"):
                providers.append("openai")
            if providers:
                missing_media_tools = [
                    tool
                    for tool in ("ffmpeg", "ffprobe")
                    if not shutil.which(tool)
                ]
                if missing_media_tools:
                    msg += (
                        " (audio transcription needs "  # seam: English UI
                        + ", ".join(missing_media_tools)  # seam: English UI
                        + ")"  # seam: English UI
                    )
                else:
                    msg += f", audio transcription ready ({'/'.join(providers)})"  # seam: English UI
        return "ok", msg

    def transcribe(
        self,
        url: str,
        *,
        provider: str = "auto",
        config=None,
        allow_provider_fallback: bool = False,
    ) -> str:
        """Download a YouTube video's audio and return its transcript.

        Delegates to :func:`agent_reach.transcribe.transcribe`. Imported lazily
        so the channel module stays cheap to import for users who never
        transcribe.
        """
        from reach.transcribe import transcribe as _transcribe  # seam: package import

        return _transcribe(
            url,
            provider=provider,
            config=config,
            allow_provider_fallback=allow_provider_fallback,
        )
# <<< LIFT
