"""browser-panel - YouTube's own caption panel read through an ALREADY-RUNNING Chrome.

The rung is get_transcript.get_transcript_browser (selenium-panel attached via
chrome_session.acquire_session). This source never launches a browser: its
check() is one loopback GET of /json/version on the debug port, the same probe
chrome_session uses, and it never attaches.
"""
from __future__ import annotations

from sources import TranscriptSource


class BrowserPanelSource(TranscriptSource):
    name = "browser-panel"
    description = "YouTube caption panel via the attached GB Chrome"
    backends = ["selenium-panel"]
    tier = 2
    kind = "caption"
    door = "cdp"
    network = False

    def rungs(self):
        import get_transcript as gt  # looked up at call time so tests can patch the rung
        return [("browser-panel", gt.get_transcript_browser, gt.DOOR_CDP)]

    def check(self, config=None):
        import chrome_session
        info = chrome_session._probe(chrome_session.DEBUG_PORT)
        if info:
            self.active_backend = "selenium-panel"
            return "ok", f"Chrome debug port {chrome_session.DEBUG_PORT} is up ({info.get('Browser', 'Chrome')})"
        self.active_backend = None
        return "off", (f"no Chrome on debug port {chrome_session.DEBUG_PORT} - start it once with "
                       "scripts/launch_chrome_debug.ps1, or select another source (--sources)")
