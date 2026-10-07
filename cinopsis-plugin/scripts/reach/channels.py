# Cinopsis reach layer - raw lift of Agent-Reach (channel / probe / doctor model) at the pinned sha.
# v3.1 (2026-10-07): the FULL upstream 16-channel registry; Cinopsis transcript sources are appended by sources.register().
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/channels/base.py:1-70
# -*- coding: utf-8 -*-
"""
Channel base class — platform availability checking.

Each channel represents a platform (YouTube, Twitter, GitHub, etc.)
and provides:
  - can_handle(url) → does this URL belong to this platform?
  - check(config) → is the upstream tool installed and configured?

After installation, agents call upstream tools directly.

Backend routing semantics:
  - `backends` is an ORDERED candidate list: backends[0] is the preferred
    backend, the rest are fallbacks. "Switching backends" for a platform
    means reordering this list (or a user override) — not rewriting code.
  - check() must set `self.active_backend` to the backend that is actually
    serving the channel right now (None when nothing usable is found).
    shutil.which() alone is NOT proof of health — a stale venv shim passes
    which() but cannot execute (see agent_reach.probe). Channels should
    really execute a lightweight command before claiming a backend active.
  - Users can force a backend with config key `<channel>_backend`
    (or env var `<CHANNEL>_BACKEND`); ordered_backends() applies it.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple


class Channel(ABC):
    """Base class for all channels."""

    name: str = ""                    # e.g. "youtube"
    description: str = ""             # e.g. "YouTube 视频和字幕"
    backends: List[str] = []          # ordered candidates — backends[0] = preferred
    tier: int = 0                     # 0=zero-config, 1=needs free key, 2=needs setup

    #: Backend currently serving this channel; set by check(), None = unavailable.
    active_backend: Optional[str] = None

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this channel can handle this URL."""
        ...

    def ordered_backends(self, config=None) -> List[str]:
        """Candidate backends in probe order, honoring the user override.

        The config key `<channel>_backend` (env `<CHANNEL>_BACKEND`) moves the
        named backend to the front of the list; unknown values are ignored so
        a stale override can never hide working backends.
        """
        candidates = list(self.backends)
        override = config.get(f"{self.name}_backend") if config else None
        if override:
            for i, b in enumerate(candidates):
                if b == override or b.startswith(override):
                    candidates.insert(0, candidates.pop(i))
                    break
        return candidates

    def check(self, config=None) -> Tuple[str, str]:
        """
        Check if this channel's upstream tool is available.
        Returns (status, message) where status is 'ok'/'warn'/'off'/'error'.

        Subclasses with external backends must really probe them (see
        agent_reach.probe.probe_command) and set self.active_backend.
        """
        self.active_backend = self.backends[0] if self.backends else "built-in"  # seam: English UI
        return "ok", f"{', '.join(self.backends) if self.backends else 'built-in'}"  # seam: English UI
# <<< LIFT

# Cinopsis seam helper (not upstream). R10 (2026-10-07): a platform channel whose check() talks to a
# public API (bilibili search, v2ex, xueqiu) asks here first. The default policy is closed, so a plain
# doctor run never touches the network. `doctor --live` opens it "once": each channel gets exactly one
# lightweight request per process. The lifted upstream tests set "always" (their transports are mocked).
# It sits between the two fences because the channel modules import it while this registry is loading.
_NETWORK_PROBE_POLICY = "closed"  # closed | once | always
_NETWORK_PROBED: set = set()


def open_network_probes(policy: str = "once") -> None:
    """Allow channel check() network probes (doctor --live)."""
    global _NETWORK_PROBE_POLICY
    _NETWORK_PROBE_POLICY = policy
    _NETWORK_PROBED.clear()


def network_probe_allowed(name: str) -> bool:
    """True when channel `name` may send its one probe request now."""
    if _NETWORK_PROBE_POLICY == "always":
        return True
    if _NETWORK_PROBE_POLICY != "once" or name in _NETWORK_PROBED:
        return False
    _NETWORK_PROBED.add(name)
    return True


# >>> LIFT agent-reach@a19a171f agent_reach/channels/__init__.py:1-65
# -*- coding: utf-8 -*-
"""
Channel registry — lists all supported platforms for doctor checks.
"""

from typing import List, Optional

# Import all channels
# Channel is defined above in this module (channels/base.py block).  # seam: base+registry share one module
from reach.bilibili import BilibiliChannel  # seam: package import
from reach.boss import BossChannel  # seam: package import
from reach.exa_search import ExaSearchChannel  # seam: package import
from reach.facebook import FacebookChannel  # seam: package import
from reach.github import GitHubChannel  # seam: package import
from reach.instagram import InstagramChannel  # seam: package import
from reach.linkedin import LinkedInChannel  # seam: package import
from reach.reddit import RedditChannel  # seam: package import
from reach.rss import RSSChannel  # seam: package import
from reach.twitter import TwitterChannel  # seam: package import
from reach.v2ex import V2EXChannel  # seam: package import
from reach.web import WebChannel  # seam: package import
from reach.xiaohongshu import XiaoHongShuChannel  # seam: package import
from reach.xiaoyuzhou import XiaoyuzhouChannel  # seam: package import
from reach.xueqiu import XueqiuChannel  # seam: package import
from reach.youtube import YouTubeChannel  # seam: package import

ALL_CHANNELS: List[Channel] = [
    GitHubChannel(),
    TwitterChannel(),
    YouTubeChannel(),
    RedditChannel(),
    FacebookChannel(),
    InstagramChannel(),
    BilibiliChannel(),
    XiaoHongShuChannel(),
    LinkedInChannel(),
    BossChannel(),
    XiaoyuzhouChannel(),
    V2EXChannel(),
    XueqiuChannel(),
    RSSChannel(),
    ExaSearchChannel(),
    WebChannel(),
]


def get_channel(name: str) -> Optional[Channel]:
    """Get a channel by name."""
    for ch in ALL_CHANNELS:
        if ch.name == name:
            return ch
    return None


def get_all_channels() -> List[Channel]:
    """Get all registered channels."""
    return ALL_CHANNELS


__all__ = [
    "Channel",
    "ALL_CHANNELS",
    "get_channel",
    "get_all_channels",
]
# <<< LIFT
