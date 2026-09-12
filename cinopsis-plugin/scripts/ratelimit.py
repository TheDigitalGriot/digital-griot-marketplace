#!/usr/bin/env python3
"""Rate-limit gate for every YouTube-touching call (anti-hammer chokepoint).

Single shared gate that ALL YouTube network routes pass through — the transcript
ladder (get_transcript / fetch_transcripts / compare_videos), the playlist pull
(fetch_playlist), the channel list (fetch_videos), and frame capture
(capture_frames). The viewer never touches YouTube and does not gate.

Contract:
  check_gate(source, door)   -> call BEFORE any YouTube request. Enforces a
                          minimum spacing between calls and REFUSES (raises
                          RateLimited) while a cooldown is active — no network
                          is touched.
  record_outcome(ok, detail, door) -> call AFTER. Success clears the streak; an
                          IpBlocked / RequestBlocked / HTTP 429 sets an
                          exponential cooldown so the next call is refused.
  reset()              -> escape hatch: clear the cooldown (e.g. after moving to
                          a clean network / different IP). Also `--reset` on CLI.

Doors: YouTube exposes two transcript routes with independent throttling — the
`timedtext` caption endpoint (Door 1, the one that IP-blocks) and the
`innertube` get_transcript panel endpoint (Door 2, historically un-throttled).
Passing `door=` cools them asymmetrically: a Door-1 block cools ONLY Door 1, so
the still-working Door 2 stays reachable; a Door-2 block means the IP is in real
trouble and cools EVERYTHING (the shared block). A third door, `cdp` (Door 3), is
the browser-driven rung: it drives a real logged-in Chrome, so an HTTP-level block
must not cool it and a cdp block cools ONLY cdp. Calls that pass no `door` behave
exactly as before — they read and arm the shared cooldown.

Fail-closed: if the state file is unreadable, the gate still enforces minimum
spacing (it never falls open to unlimited calls). State lives in DATA_DIR so it
is shared across every caller and persists across runs.
"""
import json
import os
import sys
import time
from pathlib import Path

from _utils import DATA_DIR

STATE_FILE = DATA_DIR / "fetch_ratelimit.json"

# All tunable via env; defaults chosen for a sticky residential IP block.
MIN_SPACING_S = float(os.environ.get("CINOPSIS_MIN_SPACING_S", "2.0"))
BASE_COOLDOWN_S = float(os.environ.get("CINOPSIS_BASE_COOLDOWN_S", "3600"))    # 1h
MAX_COOLDOWN_S = float(os.environ.get("CINOPSIS_MAX_COOLDOWN_S", "43200"))     # 12h

# Substrings (lowercased) in a failure detail that mean "YouTube blocked this IP".
BLOCK_MARKERS = (
    "ipblocked", "requestblocked", "request blocked", "too many requests",
    "http error 429", "429", "blocking requests from your ip",
)

# Transcript "doors" — mirrors the rung names in get_transcript.py.
DOOR_TIMEDTEXT = "timedtext"    # Door 1: /api/timedtext (the one that IP-blocks)
DOOR_INNERTUBE = "innertube"    # Door 2: youtubei/v1/get_transcript panel
# Door 3: browser-driven (CDP) — opt-in, human-paced, real logged-in Chrome with
# real cookies/session. A qualitatively different surface from an HTTP POST, so it
# survives an HTTP-door block and gets its own independent per-door cooldown.
DOOR_CDP = "cdp"


class RateLimited(Exception):
    """Raised by check_gate() when a cooldown is active — no network was touched."""

    def __init__(self, until, reason):
        self.until = until
        self.reason = reason
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(until))
        remaining = max(0, int(until - time.time()))
        super().__init__(
            f"cinopsis rate-limit gate active: cooling down until {when} "
            f"(~{remaining // 60} min left) — reason: {reason}. "
            f"Move to a clean network then run `python ratelimit.py --reset`, "
            f"or wait it out."
        )


def _load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        # Corrupt/unreadable state -> fail closed: pretend a recent call so the
        # min-spacing sleep applies; never fall open to unlimited.
        return {"last_call": time.time()}


def _doors(state):
    """Read-only per-door map. A legacy flat state (no "doors" key) reads as {}."""
    doors = state.get("doors")
    return doors if isinstance(doors, dict) else {}


def _door_entry(state, door):
    """Get-or-create the mutable per-door record for `door` inside `state`."""
    doors = state.get("doors")
    if not isinstance(doors, dict):
        doors = {}
        state["doors"] = doors
    entry = doors.get(door)
    if not isinstance(entry, dict):
        entry = {}
        doors[door] = entry
    return entry


def _door_status(state, now):
    """Summarize every known door as blocked / seconds_left / fail_streak."""
    out = {}
    for name, entry in _doors(state).items():
        if not isinstance(entry, dict):
            continue
        until = entry.get("block_until", 0)
        out[name] = {
            "blocked": bool(until and now < until),
            "block_until": until,
            "seconds_left": max(0, int(until - now)) if until else 0,
            "fail_streak": entry.get("fail_streak", 0),
            "reason": entry.get("block_reason", ""),
        }
    return out


def _save(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass  # best-effort; never crash the fetch on a state-write failure


def reset():
    """Clear all cooldown/spacing state (escape hatch for a clean network)."""
    try:
        STATE_FILE.unlink()
        return True
    except FileNotFoundError:
        return False


def status():
    """Return a human dict of the current gate state (for --status / logging).

    The shared/global keys keep their original meaning; `doors` adds a per-door
    summary and `block_door` names the door that armed the shared block (None
    when a door-less caller armed it).
    """
    st = _load()
    now = time.time()
    until = st.get("block_until", 0)
    return {
        "blocked": bool(until and now < until),
        "block_until": until,
        "seconds_left": max(0, int(until - now)) if until else 0,
        "fail_streak": st.get("fail_streak", 0),
        "reason": st.get("block_reason", ""),
        "block_door": st.get("block_door"),
        "doors": _door_status(st, now),
    }


def check_gate(source="fetch", door=None):
    """Call BEFORE any YouTube network request.

    Raises RateLimited if the shared cooldown is active, or — when `door` is
    given — if that door's own cooldown is active. No network is touched on a
    refusal, and a refusal does not consume pacing time. Otherwise enforces the
    GLOBAL minimum inter-call spacing (sleeps if needed) and returns True.
    """
    st = _load()
    now = time.time()

    until = st.get("block_until", 0)
    if until and now < until:
        raise RateLimited(until, st.get("block_reason", "cooldown"))

    if door is not None:
        entry = _doors(st).get(door)
        if isinstance(entry, dict):
            d_until = entry.get("block_until", 0)
            if d_until and now < d_until:
                raise RateLimited(
                    d_until, entry.get("block_reason", "cooldown") + f" [door={door}]"
                )

    last = st.get("last_call", 0)
    wait = MIN_SPACING_S - (now - last)
    if wait > 0:
        time.sleep(min(wait, MIN_SPACING_S))

    st["last_call"] = time.time()
    _save(st)
    return True


def record_outcome(ok, detail="", door=None):
    """Call AFTER a YouTube request.

    ok=True clears the failure streak and cooldown for the scope that owns it.
    ok=False whose `detail` matches an IP-block marker starts/extends an
    exponential cooldown, scoped by `door`:

      door=None            -> shared cooldown (legacy behavior, unchanged)
      door=DOOR_INNERTUBE  -> shared cooldown, tagged as armed by innertube
      any other door       -> that door only; the shared cooldown is untouched
    """
    st = _load()
    st["last_call"] = time.time()
    detail_l = (detail or "").lower()
    is_block = (not ok) and any(m in detail_l for m in BLOCK_MARKERS)

    if ok:
        if door is not None:
            entry = _door_entry(st, door)
            entry["fail_streak"] = 0
            entry.pop("block_until", None)
            entry.pop("block_reason", None)
        # Only the door that armed the shared block may clear it (None == None).
        if st.get("block_door") == door:
            st["fail_streak"] = 0
            st.pop("block_until", None)
            st.pop("block_reason", None)
            st.pop("block_door", None)
    elif is_block:
        if door is None or door == DOOR_INNERTUBE:
            # Door 2 blocking means the IP itself is in trouble — cool everything.
            streak = int(st.get("fail_streak", 0)) + 1
            st["fail_streak"] = streak
            cooldown = min(BASE_COOLDOWN_S * (2 ** (streak - 1)), MAX_COOLDOWN_S)
            st["block_until"] = time.time() + cooldown
            st["block_reason"] = (detail or "IP block")[:160]
            st["block_door"] = door
        else:
            entry = _door_entry(st, door)
            streak = int(entry.get("fail_streak", 0)) + 1
            entry["fail_streak"] = streak
            cooldown = min(BASE_COOLDOWN_S * (2 ** (streak - 1)), MAX_COOLDOWN_S)
            entry["block_until"] = time.time() + cooldown
            entry["block_reason"] = (detail or "IP block")[:160]
    _save(st)
    return status()


def _main(argv):
    if "--reset" in argv:
        print("reset (shared + all doors cleared)" if reset() else "nothing to reset")
        return 0
    # default: print status (includes the per-door breakdown)
    print(json.dumps(status(), indent=2))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(_main(sys.argv[1:]))
