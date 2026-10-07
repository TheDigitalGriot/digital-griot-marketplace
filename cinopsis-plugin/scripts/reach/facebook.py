# Cinopsis reach layer - raw lift of Agent-Reach at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/channels/facebook.py:1-13
# -*- coding: utf-8 -*-
"""Facebook — OpenCLI backend using the user's logged-in Chrome session."""

from reach._opencli_site import OpenCLISiteChannel  # seam: package import


class FacebookChannel(OpenCLISiteChannel):
    name = "facebook"
    description = "Facebook 帖子、主页和群组"
    site = "facebook"
    domains = ("facebook.com", "fb.com", "fb.watch")
    usage = "opencli facebook search/profile/feed/groups -f yaml"
    login_hint = "facebook.com"
# <<< LIFT
