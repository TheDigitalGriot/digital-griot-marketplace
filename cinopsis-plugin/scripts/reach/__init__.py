# Cinopsis reach layer - raw lift of Agent-Reach (channel / probe / doctor model) at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/__init__.py:1-9
# -*- coding: utf-8 -*-
"""Agent Reach — Give your AI Agent eyes to see the entire internet."""

__version__ = "1.5.0"
__author__ = "Neo Reid"

from reach.core import AgentReach  # seam: package import

__all__ = ["AgentReach"]
# <<< LIFT
