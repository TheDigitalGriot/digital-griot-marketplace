# Cinopsis reach layer - raw lift of Agent-Reach at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/backends/__init__.py:1-16
# -*- coding: utf-8 -*-
"""Cross-channel backends.

A backend here is an upstream runtime that serves MULTIPLE channels
(e.g. OpenCLI covers xiaohongshu/reddit/bilibili/twitter through one
browser session), as opposed to the per-platform tools probed inside
each channel file.
"""

from reach.opencli import (  # noqa: F401  # seam: package import
    OPENCLI_EXTENSION_URL,
    OPENCLI_PACKAGE,
    OpenCLIStatus,
    opencli_status,
    opencli_summary,
)
# <<< LIFT
