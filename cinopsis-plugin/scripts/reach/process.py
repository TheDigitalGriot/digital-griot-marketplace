# Cinopsis reach layer - raw lift of Agent-Reach (channel / probe / doctor model) at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/utils/process.py:1-26
"""Subprocess helpers for consistent cross-platform text handling."""

from __future__ import annotations

import os
from collections.abc import Mapping

UTF8_ENV = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
}


def utf8_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that forces Python child processes into UTF-8 mode."""
    env = dict(base or os.environ)
    env.update(UTF8_ENV)
    return env


def mcporter_utf8_env_args() -> list[str]:
    """Return mcporter --env arguments for UTF-8 Python stdio servers."""
    args = []
    for key, value in UTF8_ENV.items():
        args.extend(["--env", f"{key}={value}"])
    return args
# <<< LIFT
