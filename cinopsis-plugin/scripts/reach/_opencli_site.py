# Cinopsis reach layer - raw lift of Agent-Reach at the pinned sha.
# Upstream logic is verbatim between the LIFT fences; every changed line ends in '# seam:'.
# Gate: python scripts/verify_lift.py

# >>> LIFT agent-reach@a19a171f agent_reach/channels/_opencli_site.py:1-47
# -*- coding: utf-8 -*-
"""Shared channel helper for OpenCLI browser-session-only platforms."""

from reach.url import host_matches  # seam: package import

from reach.channels import Channel  # seam: package import


class OpenCLISiteChannel(Channel):
    """A platform served directly by OpenCLI.

    These channels are intentionally thin: Agent Reach only installs,
    health-checks, and routes. Agents call `opencli <site> ...` directly.
    """

    site: str = ""
    domains: tuple[str, ...] = ()
    usage: str = ""
    login_hint: str = ""

    backends = ["OpenCLI"]
    tier = 1

    def can_handle(self, url: str) -> bool:
        return host_matches(url, *self.domains)

    def check(self, config=None):
        from reach.backends import opencli_status  # seam: package import

        self.active_backend = None
        st = opencli_status()
        if not st.installed:
            return "off", (
                f"未安装 {self.description} 后端。安装：\n"
                "  agent-reach install --system --channels opencli\n"
                f"然后在 Chrome 里登录 {self.login_hint}"
            )
        if st.broken:
            return "error", st.hint

        if st.ready:
            return "warn", (
                f"OpenCLI 桥接已连接，但 {self.description} 的登录态和实际命令"
                "未实时验证；Doctor 不执行平台命令，因此当前不标记为可用。"
                f"需要时请先在 Chrome 里登录 {self.login_hint}"
            )
        return "warn", st.hint
# <<< LIFT
