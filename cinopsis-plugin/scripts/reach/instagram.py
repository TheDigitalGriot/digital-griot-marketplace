# Cinopsis reach layer - raw lift of Agent-Reach at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/channels/instagram.py:1-13
# -*- coding: utf-8 -*-
"""Instagram — OpenCLI backend using the user's logged-in Chrome session."""

from reach._opencli_site import OpenCLISiteChannel  # seam: package import


class InstagramChannel(OpenCLISiteChannel):
    name = "instagram"
    description = "Instagram 用户、主页和指定用户帖子"
    site = "instagram"
    domains = ("instagram.com", "instagr.am")
    usage = "opencli instagram search/profile/user/explore -f yaml"
    login_hint = "instagram.com"
# <<< LIFT
