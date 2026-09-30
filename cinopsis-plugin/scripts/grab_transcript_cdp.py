#!/usr/bin/env python3
"""
grab_transcript_cdp.py - guaranteed-fallback transcript rung for Cinopsis.

When every pure-HTTP transcript door (youtube-transcript-api, yt-dlp, the
InnerTube get_transcript endpoint) fails, this drives a REAL logged-in Chrome
over the DevTools Protocol (CDP), opens the video's transcript panel like a
human would, and reads the segments straight out of the DOM. This is the
method that provably worked (474 segments) on a rate-limit-flagged residential
IP where every HTTP door was refused.

Session acquisition (which Chrome, which profile, attach-vs-launch, the
profile-lock problem) is NOT owned here - it is chrome_session.py's job (D3,
"ONE ORIGINAL"), shared verbatim with panel_transcript.py. This module only
drives the transcript panel once it has a browser websocket endpoint.

  - windowed, never headless -- headless does not render the transcript
    panel (confirmed live, F3).
  - ON by default (Gavin's call, 2026-09-18) - see cdp_enabled()'s docstring
    for why the old opt-in-only default was itself the root cause of the
    outage this contract fixes. $CINOPSIS_ENABLE_CDP=0 opts back out.

Usage:
  python grab_transcript_cdp.py --video-id XXXXXXXXXXX
"""
import argparse
import json   # used by the CDP transport (ws send/recv) and the click template
import os
import sys
import time

import chrome_session

_FALSY = {"0", "false", "no", "off"}
ENABLE_ENV = "CINOPSIS_ENABLE_CDP"


def cdp_enabled():
    """True unless $CINOPSIS_ENABLE_CDP is explicitly set to a falsy value.

    ON BY DEFAULT (flipped 2026-09-18). The old default was opt-in-only, and
    F1 root-caused the entire multi-week YT-playlist outage to exactly that:
    the rung built to survive an IP flag never ran because nothing ever set
    the flag. Turning it on is the fix, not a workaround - see
    chrome_session.py for why this no longer risks an unwanted browser
    launch: with Chrome already open (the common case, per Gavin), this rung
    ATTACHES to the existing session instead of spawning a new window.
    $CINOPSIS_ENABLE_CDP=0/false/off remains the escape hatch for a
    non-interactive context with no display.
    """
    val = os.environ.get(ENABLE_ENV, "").strip().lower()
    if val in _FALSY:
        return False
    return True


# ---------------------------------------------------------------------------
# Minimal CDP request/response transport over one websocket connection.
# ---------------------------------------------------------------------------
class _CDP:
    """Thin CDP client: one websocket, monotonic message ids, session routing.

    `send` blocks until the response carrying the SAME id comes back (ids are
    unique for the life of the connection, so no explicit sessionId matching
    on the reply is needed -- only on the outgoing message, per the CDP
    flattened-session convention).
    """

    def __init__(self, ws):
        self.ws = ws
        self._next_id = 0

    def send(self, method, params=None, session_id=None, timeout=30):
        self._next_id += 1
        msg_id = self._next_id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self.ws.send(json.dumps(payload))

        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                self.ws.settimeout(remaining)
                raw = self.ws.recv()
            except Exception as e:
                raise RuntimeError("CDP transport error waiting for %s: %s" % (method, e))
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError("CDP error for %s: %s" % (method, msg["error"]))
                return msg.get("result", {})
        raise RuntimeError("CDP timeout waiting for response to %s" % method)


# ---------------------------------------------------------------------------
# In-page JS snippets, driven via Runtime.evaluate. Polling a small click/query
# snippet is far more robust than computing coordinates for
# Input.dispatchMouseEvent.
# ---------------------------------------------------------------------------
_CLICK_JS_TMPL = """
(function() {
  var el = document.querySelector(%s);
  if (el) { el.click(); return true; }
  return false;
})()
"""

_SEGMENTS_JS = """
(function() {
  var nodes = document.querySelectorAll('ytd-transcript-segment-renderer');
  var out = [];
  nodes.forEach(function(n) {
    var ts = n.querySelector('.segment-timestamp');
    var txt = n.querySelector('.segment-text');
    out.push([ts ? ts.textContent.trim() : '', txt ? txt.textContent.trim() : '']);
  });
  return JSON.stringify(out);
})()
"""


def _evaluate(cdp, session_id, expression):
    result = cdp.send(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True},
        session_id=session_id,
    )
    return (result or {}).get("result", {}).get("value")


def _poll(cdp, session_id, expression, deadline, interval=0.5):
    """Poll a JS expression until it returns a truthy value or the deadline passes."""
    while time.time() < deadline:
        try:
            value = _evaluate(cdp, session_id, expression)
            if value:
                return value
        except Exception:
            pass
        time.sleep(interval)
    return None


def _poll_click(cdp, session_id, selector, deadline, interval=0.5):
    expr = _CLICK_JS_TMPL % json.dumps(selector)
    return _poll(cdp, session_id, expr, deadline, interval)


def _poll_segments(cdp, session_id, deadline, interval=1.0):
    raw = _poll(cdp, session_id, _SEGMENTS_JS, deadline, interval)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data or None


# ---------------------------------------------------------------------------
# Shared timeout budget helper -- one deadline computed once in grab(), threaded
# into every blocking call (websocket discovery/connect, every cdp.send()) so a
# hung Chrome can never stack multiple independent per-call timeouts past the
# documented `timeout=` budget.
# ---------------------------------------------------------------------------
def _remaining(deadline):
    return max(0.0, deadline - time.time())


def _send_bounded(cdp, method, params=None, session_id=None, deadline=None):
    """cdp.send() bounded by whatever is left of the shared deadline.

    Raises RuntimeError (caught by grab()'s own except Exception) the instant
    the budget is already exhausted, instead of letting the call use its own
    independent default timeout.
    """
    remaining = _remaining(deadline)
    if remaining <= 0:
        raise RuntimeError("CDP timeout budget exhausted before %s" % method)
    return cdp.send(method, params, session_id=session_id, timeout=remaining)


# ---------------------------------------------------------------------------
# Timestamp parsing: "MM:SS" / "H:MM:SS" (the panel's format) -> float seconds.
# Pure -- no network, no side effects.
# ---------------------------------------------------------------------------
def parse_timestamp(ts):
    if not ts or not isinstance(ts, str):
        return 0.0
    bits = ts.strip().split(":")
    try:
        nums = [float(b) for b in bits]
    except ValueError:
        return 0.0
    if len(nums) == 3:
        h, m, s = nums
        return h * 3600.0 + m * 60.0 + s
    if len(nums) == 2:
        m, s = nums
        return m * 60.0 + s
    if len(nums) == 1:
        return nums[0]
    return 0.0


# ---------------------------------------------------------------------------
# grab() -- the CDP rung itself. Returns plain text, or None on ANY failure.
# ---------------------------------------------------------------------------
def grab(video_id, timeout=45):
    """Drive Gavin's Chrome Profile 1 to the video's transcript panel and
    return the transcript as text, or None on any failure (opt-in disabled,
    Chrome missing, timeout, panel never appeared, etc).

    Each line of the returned text is "<panel timestamp>\\t<caption text>" --
    get_transcript_cdp() parses this back into the ladder's normalized shape.
    """
    # ONE shared budget for the whole call -- computed here, before Chrome is
    # even launched, and threaded into every blocking call below so a hung
    # Chrome can never stack independent per-call timeouts past `timeout`.
    deadline = time.time() + timeout

    if not cdp_enabled():
        print(f"[cdp] {ENABLE_ENV}=0; skipping CDP rung (explicitly disabled)", flush=True)
        return None

    proc = None
    owns_process = False
    ws = None
    session_id = None
    target_id = None
    try:
        remaining = _remaining(deadline)
        if remaining <= 0:
            print("[cdp] timeout budget exhausted before session acquisition", flush=True)
            return None
        try:
            browser_ws_url, owns_process, proc = chrome_session.acquire_session(timeout=remaining)
        except chrome_session.ChromeProfileLockedError as e:
            print(f"[cdp] {e}", flush=True)
            return None

        import websocket  # websocket-client

        remaining = _remaining(deadline)
        if remaining <= 0:
            print("[cdp] timeout budget exhausted before websocket connect", flush=True)
            return None
        ws = websocket.create_connection(browser_ws_url, timeout=remaining)
        cdp = _CDP(ws)

        url = f"https://www.youtube.com/watch?v={video_id}"
        created = _send_bounded(cdp, "Target.createTarget", {"url": url}, deadline=deadline)
        target_id = created.get("targetId")
        if not target_id:
            print("[cdp] Target.createTarget returned no targetId", flush=True)
            return None

        attached = _send_bounded(
            cdp, "Target.attachToTarget", {"targetId": target_id, "flatten": True}, deadline=deadline
        )
        session_id = attached.get("sessionId")
        if not session_id:
            print("[cdp] Target.attachToTarget returned no sessionId", flush=True)
            return None

        _send_bounded(cdp, "Page.enable", session_id=session_id, deadline=deadline)
        _send_bounded(cdp, "Runtime.enable", session_id=session_id, deadline=deadline)

        _poll(cdp, session_id, "document.readyState === 'complete'", deadline)

        # Drive the panel open: expand the description, then open the transcript.
        _poll_click(cdp, session_id, "#expand", deadline)
        _poll_click(cdp, session_id, 'button[aria-label="Show transcript"]', deadline)

        segments = _poll_segments(cdp, session_id, deadline)
        if not segments:
            print("[cdp] transcript panel never populated", flush=True)
            return None

        lines = []
        for entry in segments:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            ts, text = entry
            text = (text or "").strip()
            if not text:
                continue
            lines.append(f"{(ts or '').strip()}\t{text}")

        if not lines:
            return None
        print(f"[cdp] captured {len(lines)} segments", flush=True)
        return "\n".join(lines)
    except Exception as e:
        print(f"[cdp] grab failed: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        # Ownership contract (chrome_session.py): close only the TARGET we
        # opened, always -- but only terminate the whole Chrome PROCESS when
        # this call launched it itself. An attached session is Gavin's live
        # browser (or a prior cinopsis run's); tearing it down out from under
        # him is exactly the failure this module exists to never cause again.
        if ws is not None and session_id and target_id:
            try:
                _send_bounded(cdp, "Target.closeTarget", {"targetId": target_id}, deadline=time.time() + 5)
            except Exception:
                pass
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if owns_process and proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


# ---------------------------------------------------------------------------
# Ladder-shaped adapter.
# ---------------------------------------------------------------------------
def get_transcript_cdp(video_id):
    """Ladder adapter: (transcript, lang) or (None, None) on failure.

    Normalized shape: [{"start": <float seconds>, "text": <str>}, ...] -- no
    "duration" key, matching every other rung. MUST NEVER raise (including
    SystemExit) -- wrapped so nothing escapes.
    """
    try:
        text = grab(video_id)
        if not text:
            return None, None

        transcript = []
        for line in text.split("\n"):
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            ts, caption = parts
            caption = caption.strip()
            if not caption:
                continue
            transcript.append({"start": parse_timestamp(ts), "text": caption})

        if not transcript:
            return None, None
        return transcript, "en"
    except (Exception, SystemExit):
        # SystemExit is caught explicitly alongside Exception so the "never
        # raises, including SystemExit" guarantee holds -- but KeyboardInterrupt
        # (also a BaseException) is deliberately left to propagate, so Ctrl+C
        # stays responsive while this rung runs (including the interactive
        # manual-test path via main()).
        return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Fetch a YouTube transcript via a real Chrome + CDP (guaranteed-fallback rung)"
    )
    parser.add_argument("--video-id", required=True, help="YouTube video ID")
    parser.add_argument("--port", type=int, default=chrome_session.DEBUG_PORT,
                         help="Chrome remote-debugging port")
    args = parser.parse_args()
    chrome_session.DEBUG_PORT = args.port

    transcript, lang = get_transcript_cdp(args.video_id)
    if not transcript:
        print(
            "CDP transcript grab failed. Check that CINOPSIS_ENABLE_CDP is not set to "
            "0/false, Chrome is installed, and Profile 1 is signed into YouTube."
        )
        sys.exit(1)

    print(f"Transcript: {lang}, {len(transcript)} entries")
    for seg in transcript[:5]:
        print(f"  [{seg['start']:.1f}] {seg['text']}")


if __name__ == "__main__":
    main()
