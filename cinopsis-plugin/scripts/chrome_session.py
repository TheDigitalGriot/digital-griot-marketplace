#!/usr/bin/env python3
"""chrome_session.py - the ONE session-acquisition seam for Cinopsis's panel
rungs (D3, "ONE ORIGINAL" - Gavin, 2026-09-18: "this is exactly what i meant
when i said ONE ORIGINAL").

Both panel rungs - grab_transcript_cdp.py (raw CDP) and panel_transcript.py
(Selenium) - get their Chrome session from `acquire_session()` in this module
and nowhere else. Neither may launch its own Chrome process, point at its own
profile directory, or inject its own cookie jar. That forking (F4) is exactly
what left one rung signed-in and Premium and the other signed-out and useless.

## Which profile, and why (D2)

Chrome PROFILE 1 = "Gavin" = gbdevux@gmail.com = the GB profile = the one
carrying his YouTube Premium session. Locked in by Gavin, explicitly OVER:
  - the exported cookie jar (export_yt_cookies.py / resolve_cookies()) - a
    copy of a session, and already what F4's rejected fork relied on,
  - a profile COPY refreshed from Profile 1,
  - cinopsis's own dedicated "yt-profile" (what grab_transcript_cdp.py used
    until this fix - no lock conflict, but signed OUT, which is the F3/F4
    failure this exists to repair).

## The profile-lock problem (the open problem this module solves)

Chrome enforces a SINGLETON LOCK per --user-data-dir: a second process
pointed at a directory another Chrome process already owns cannot start.
Gavin's GB Chrome is normally OPEN on Profile 1, so naively launching
Chrome with --user-data-dir=...\\User Data --profile-directory="Profile 1"
crashes (observed: chromedriver's GetHandleVerifier stack, exit 1) exactly
when the panel rungs matter most.

Alternatives evaluated, and why each lost:
  - Profile COPY refreshed from Profile 1. Rejected by D2 (not "Profile 1"
    itself). Also fragile even if it had been chosen: Chrome's cookie/
    login-data stores are SQLite with WAL journaling, so copying the files
    while Profile 1 is open risks a torn read, and Chrome 127+'s App-Bound
    Encryption ties some values to the machine+process, not just the file -
    a copy is not guaranteed to decrypt.
  - Cookie-jar injection into a throwaway profile (what panel_transcript.py
    forked into before today, via prime_session() + export_yt_cookies).
    Rejected by D2 for the same reason - it is a copy, not Profile 1 - and
    it is also the ONE ORIGINAL violation F4 flags.
  - Telling Gavin to close Chrome before a batch. Duct tape, explicitly
    rejected in the contract ("this is duct tape").

WINNER: attach-first, launch-fallback over a CDP debug port.
  1. ATTACH - probe the well-known debug port first. If a Chrome is already
     listening there (Gavin's own browser, started via
     launch_chrome_debug.ps1 or a prior cinopsis run), attach to THAT
     process. No new process is spawned, so there is no lock to fight, and
     it is by definition his live, signed-in, Premium session. An attached
     session is NEVER terminated by this module - see the ownership contract
     below.
  2. LAUNCH - nothing answered the port, so try to start Chrome on Profile 1
     ourselves with the debug port already on. This only fails when Profile
     1 is open in ANOTHER process that was not started with a debug port -
     see (3).
  3. LOCKED - that one remaining case is a real Chrome limitation, not a
     Cinopsis bug to route around: Chromium provides no IPC/signal to turn
     on remote debugging for an already-running instance, on any OS (the
     port can only be set at process launch). The durable, one-time fix is
     launch_chrome_debug.ps1 - Gavin runs it once (or pins it to his normal
     shortcut) to open Chrome on Profile 1 WITH the debug port already open;
     every later run then hits branch 1 and never touches the lock again.
     acquire_session() raises ChromeProfileLockedError with that fix spelled
     out in the message rather than crashing opaquely.

## Ownership contract (read this before calling driver.quit() / terminating)

`acquire_session()` returns `(browser_ws_url, owns_process, proc)`.
  - owns_process=False (ATTACHED): this module did not start the browser.
    Callers must close only the target/tab they opened (CDP
    Target.closeTarget, or Selenium driver.close() on its own window handle)
    and must NEVER call driver.quit() / terminate the process - that can
    tear down Gavin's whole browser out from under him.
  - owns_process=True (LAUNCHED): this module started a dedicated Chrome
    process for the caller. It is safe (and expected) to close it fully when
    done - driver.quit() or proc.terminate().
"""
import json
import os
import subprocess
import time
from urllib.request import urlopen

from export_yt_cookies import find_chrome  # Chrome-binary discovery only - generic, not profile-specific

# Gavin's primary Chrome profile (D2). Overridable for testing / a different
# machine layout via the same env vars panel_transcript.py already exposed.
_DEFAULT_USER_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
USER_DATA_DIR = os.environ.get("CINOPSIS_CHROME_USER_DATA", _DEFAULT_USER_DATA_DIR)
PROFILE_DIRECTORY = os.environ.get("CINOPSIS_CHROME_PROFILE", "Profile 1")

# ONE shared debug port for Profile-1 panel sessions - distinct from
# export_yt_cookies.py's 9222 (a DIFFERENT, dedicated cookie-export profile),
# so a cookie export and a panel session can never collide even if both run
# at once. Reuses the port grab_transcript_cdp.py already used for its own
# (now-retired) dedicated profile, so nothing new needs opening in a firewall.
DEBUG_PORT = int(os.environ.get("CINOPSIS_PANEL_CDP_PORT", "9333"))


class ChromeProfileLockedError(RuntimeError):
    """Profile 1 is open in another Chrome process with no debug port, so we
    can neither attach (nothing is listening) nor launch (the OS-level
    singleton lock refuses a second process on that user-data-dir). The
    message carries the one-time fix (launch_chrome_debug.ps1)."""


def _probe(port, timeout=2):
    """GET /json/version. Returns the parsed dict, or None on any failure."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def _wait_for_port(port, deadline):
    while time.time() < deadline:
        info = _probe(port)
        if info:
            return info
        time.sleep(0.5)
    return None


def acquire_session(timeout=25):
    """Return (browser_ws_url, owns_process, proc_or_None).

    See the module docstring's "Ownership contract" before deciding whether
    to close/quit/terminate what this returns.

    Raises ChromeProfileLockedError when Profile 1 is locked by another
    process with no debug port open (see "LOCKED" above) - never returns a
    silently-broken session.
    """
    # 1. ATTACH.
    info = _probe(DEBUG_PORT)
    if info and info.get("webSocketDebuggerUrl"):
        print(f"  [chrome-session] attached to existing Chrome on Profile 1 "
              f"(port {DEBUG_PORT})", flush=True)
        return info["webSocketDebuggerUrl"], False, None

    # 2. LAUNCH.
    try:
        chrome = find_chrome()
    except SystemExit as e:
        # find_chrome() calls sys.exit() when Chrome isn't found anywhere on
        # the machine. SystemExit is BaseException, not Exception - caught
        # and re-raised as a plain RuntimeError here so every caller's normal
        # `except Exception` handles "no Chrome" the same way it handles any
        # other acquisition failure, instead of each rung needing its own
        # SystemExit special-case (grab_transcript_cdp.py used to carry one).
        raise RuntimeError(f"Chrome not found: {e}") from e
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    args = [
        chrome,
        "--user-data-dir=" + USER_DATA_DIR,
        "--profile-directory=" + PROFILE_DIRECTORY,
        "--remote-debugging-port=" + str(DEBUG_PORT),
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "about:blank",
    ]
    # WINDOWED - NEVER headless. Headless withholds the transcript panel
    # (confirmed live, F3): same video, same scraper, same minute,
    # headed=True -> 237 segments, headed=False -> 0 ("no panel"). That reads
    # exactly like an IP block and is not one - do not add --headless here.
    print(f"  [chrome-session] launching Chrome on Profile 1 (port {DEBUG_PORT})...",
          flush=True)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + timeout
    info = _wait_for_port(DEBUG_PORT, deadline)
    if info and info.get("webSocketDebuggerUrl"):
        return info["webSocketDebuggerUrl"], True, proc

    # 3. LOCKED.
    try:
        proc.poll()
        exited = proc.returncode is not None
    except Exception:
        exited = True
    raise ChromeProfileLockedError(
        f"Chrome Profile 1 did not expose a CDP debug port within {timeout}s "
        f"({'process exited' if exited else 'still running, no port'}). This is "
        "Chrome's per-profile singleton lock: Profile 1 is already open in "
        "another Chrome process that was not started with "
        "--remote-debugging-port, and Chromium has no way to turn debugging on "
        "for an already-running instance (true on every OS - the port can only "
        "be set at launch). One-time fix: run scripts/launch_chrome_debug.ps1 "
        "once to (re)open Chrome on Profile 1 with the debug port already on "
        "(or pin it to Gavin's normal Chrome shortcut) - every later cinopsis "
        "run then ATTACHES instead of trying to launch, and this error stops "
        "happening for good."
    )
