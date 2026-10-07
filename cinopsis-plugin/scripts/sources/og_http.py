"""og-http - the original HTTP ladder: innertube, youtube-transcript-api, yt-dlp, cdp-panel, asr.

Selecting og-http on its own (--sources og-http) runs these rungs WITHOUT the
browser rung first, and a missing Chrome never aborts them (the v2.9 defect:
--allow-http-rungs could not reach these rungs while no CDP port was open).
"""
from __future__ import annotations

from reach.probe import probe_command
from sources import TranscriptSource


class OgHttpSource(TranscriptSource):
    name = "og-http"
    description = "Original HTTP ladder (innertube / transcript-api / yt-dlp / cdp / asr)"
    backends = ["innertube", "api", "yt-dlp", "cdp-panel", "asr"]
    tier = 0
    kind = "caption"
    door = None  # per rung: innertube / timedtext / cdp

    def rungs(self):
        import get_transcript as gt
        return list(gt._legacy_http_rungs())

    def check(self, config=None):
        from _utils import find_ytdlp
        import ratelimit
        probe = probe_command(find_ytdlp(), ["--version"], timeout=10, package="yt-dlp")
        st = ratelimit.status()
        cooling = [d for d, v in (st.get("doors") or {}).items()
                   if isinstance(v, dict) and (v.get("seconds_left") or 0) > 0]
        if st.get("blocked"):
            cooling.append("shared")
        self.active_backend = "innertube"
        note = f"yt-dlp {probe.output.splitlines()[0] if probe.ok and probe.output else probe.status}"
        if cooling:
            return "warn", f"{note}; cooling doors: {', '.join(sorted(cooling))} (rungs on those doors skip)"
        return "ok", f"{note}; all doors open"
