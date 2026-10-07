# Cinopsis reach layer - raw lift of Agent-Reach (channel / probe / doctor model) at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/core.py:1-42
# -*- coding: utf-8 -*-
"""
AgentReach — installer, doctor, and configuration tool.

Agent Reach helps AI agents install and configure upstream platform tools
(twitter-cli, yt-dlp, mcporter, gh CLI, etc.). After installation, agents
call the upstream tools directly — no wrapper layer needed.

Usage:
    from reach.doctor import check_all, format_report  # seam: package import
    from reach.config import Config  # seam: package import

    config = Config()
    results = check_all(config)
    print(format_report(results))
"""

from typing import Dict, Optional

from reach.config import Config  # seam: package import


class AgentReach:
    """Give your AI Agent eyes to see the entire internet.

    This class provides health-check functionality.
    For reading/searching, use the upstream tools directly
    (see SKILL.md for commands).
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()

    def doctor(self) -> Dict[str, dict]:
        """Check all channel availability."""
        from reach.doctor import check_all  # seam: package import
        return check_all(self.config)

    def doctor_report(self) -> str:
        """Get formatted health report."""
        from reach.doctor import check_all, format_report  # seam: package import
        return format_report(check_all(self.config))
# <<< LIFT
