#!/usr/bin/env python3
"""chrome_session.py - the ONE session-acquisition seam for Cinopsis's browser
transcript path (D3, "ONE ORIGINAL" - Gavin, 2026-09-18: "this is exactly what i
meant when i said ONE ORIGINAL").

Every browser reader - panel_transcript.py (Selenium, the DEFAULT and only
auto-used transcript path) and the legacy grab_transcript_cdp.py (raw CDP) -
gets its Chrome session from `acquire_session()` in this module and nowhere
else. Neither may launch its own Chrome process, point at its own profile
directory, or inject its own cookie jar.

## ATTACH-ONLY (stage contract transcript-browser-default, H0 / D5)

Cinopsis NEVER LAUNCHES A BROWSER. Gavin has said this repeatedly; it is the
hardest rule in the contract. `acquire_session()` does exactly one thing:
probe the well-known CDP debug port and, if his ALREADY-RUNNING Chrome is
listening there, hand back its websocket URL. If nothing is listening it
RAISES `ChromeProfileLockedError` (F1) and stops - no launch, no retry, no
fallback to an HTTP transcript door.

Until 2026-10-01 this module had a LAUNCH branch (start Chrome on Profile 1
with the debug port on, and fall through to the lock error only if that
failed). That branch is removed on purpose: opening a window on his desktop to
"make it work" is the exact behaviour he forbade. It remains in git history.

## Which profile (D2)

Chrome PROFILE 1 = "Gavin" = gbdevux@gmail.com = the GB profile = the one
carrying his YouTube Premium session. Attaching to his own running browser is
by definition that live, signed-in session; no cookie jar, profile copy or
throwaway profile is involved.

## Why a debug port has to exist already (F1)

Chrome enforces a SINGLETON LOCK per user-data directory, and Chromium provides no
IPC/signal to turn on remote debugging for an already-running instance, on any
OS (the port can only be set at process launch). So if Gavin's Chrome is open
WITHOUT --remote-debugging-port there is nothing to attach to. The durable,
one-time fix is scripts/launch_chrome_debug.ps1 - HE runs it once (or pins the
flag to his normal Chrome shortcut); every later cinopsis run then attaches.

## Ownership contract

`acquire_session()` returns `(browser_ws_url, owns_process, proc)`. Because this
module never starts a browser, `owns_process` is ALWAYS False and `proc` is
ALWAYS None; the tuple shape is kept for existing callers. Callers close only
the tab/target THEY opened (CDP Target.closeTarget, or Selenium driver.close())
and must NEVER call driver.quit() / terminate the process - that would tear
down Gavin's whole browser out from under him.
"""
import json
import os
from urllib.request import urlopen

# ONE shared debug port for the Profile-1 browser session - distinct from
# export_yt_cookies.py's 9222 (a DIFFERENT, dedicated cookie-export profile),
# so a cookie export and a panel session can never collide even if both run
# at once. scripts/launch_chrome_debug.ps1 reads the same env var.
DEBUG_PORT = int(os.environ.get("CINOPSIS_PANEL_CDP_PORT", "9333"))


class ChromeProfileLockedError(RuntimeError):
    """F1. No Chrome is listening on the CDP debug port, so there is nothing to
    attach to - and Cinopsis never launches one. Almost always this means Chrome
    Profile 1 is already open WITHOUT --remote-debugging-port. The message
    carries the one-time fix (scripts/launch_chrome_debug.ps1). This error must
    NEVER be answered by falling back to an HTTP transcript door."""


def _probe(port, timeout=2):
    """GET /json/version on the LOCAL debug port. Returns the parsed dict, or
    None on any failure. Loopback only - this never touches YouTube."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def f1_message(port=None):
    """The F1 text. One function so every surface says the same thing."""
    port = DEBUG_PORT if port is None else port
    return (
        f"No Chrome is listening on CDP debug port {port}. Cinopsis only ever "
        "ATTACHES to your already-running Chrome and never launches a browser. "
        "Chrome Profile 1 is most likely already open WITHOUT "
        "--remote-debugging-port, and Chromium cannot turn debugging on for a "
        "running instance (true on every OS - the port can only be set at "
        "launch). One-time fix: run scripts/launch_chrome_debug.ps1 once (or "
        "pin that flag to your normal Chrome shortcut) - every later cinopsis "
        "run then ATTACHES. Cinopsis did NOT fall back to an HTTP transcript "
        "door (they are disabled by default; see CINOPSIS_ALLOW_HTTP_RUNGS)."
    )


def acquire_session(timeout=25):
    """Return (browser_ws_url, False, None) by ATTACHING to the running Chrome.

    `timeout` is accepted for signature compatibility with existing callers and
    is unused: there is exactly one loopback probe and no waiting for a browser
    to start, because none is ever started.

    Raises ChromeProfileLockedError (F1) when nothing answers the debug port.
    Never launches a process. Never returns a silently-broken session.
    """
    info = _probe(DEBUG_PORT)
    if info and info.get("webSocketDebuggerUrl"):
        print(f"  [chrome-session] attached to existing Chrome on Profile 1 "
              f"(port {DEBUG_PORT})", flush=True)
        return info["webSocketDebuggerUrl"], False, None
    raise ChromeProfileLockedError(f1_message())
