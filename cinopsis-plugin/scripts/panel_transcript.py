#!/usr/bin/env python
"""panel_transcript.py -- THE browser transcript path. The default, and the only
auto-used way Cinopsis acquires a transcript (stage contract
transcript-browser-default, D1).

It reads YouTube's on-page transcript PANEL in Gavin's ALREADY-RUNNING Chrome,
so it never touches the HTTP doors (timedtext / youtubei / yt-dlp) whose
repeated use IP-blocked his residential address.

## HARD CONSTRAINT (H0) - this module never launches a browser

The only browser interaction here is ATTACHING: `chrome_session.acquire_session()`
+ Selenium's `Options.debugger_address` on the existing debug port. If no debug
port answers, `ChromeProfileLockedError` (F1) is raised and everything stops -
no launch, no retry, no HTTP fallback.

## THE PROVEN RECIPE (verified live 2026-09-30 on 7/7 videos, incl. an 86-minute
## webinar: 80 / 304 / 135 / 171 / 51 / 196 / 807 rows) - encoded here ONCE so
## every caller shares it:

  R1  expand the description (#expand), wait ~400ms
  R2  open the panel: button[aria-label="Show transcript"] -> "Transcript" ->
      first <button> whose text+aria-label matches /show transcript/i
  R3  the panel is ytd-engagement-panel-section-list-renderer
      [target-id="engagement-panel-searchable-transcript"]
  R4  THE PANEL OPENS ON THE "CHAPTERS" TAB. Click the leaf whose trimmed text is
      exactly "Transcript" (walk up <=4 ancestors to a BUTTON / [role=tab]).
      Without this click the panel reports EXPANDED and yields zero rows forever
      - the #1 cause of a 0-row read.
  R5  PATIENT SPINNER WAIT: 14 polls x 2200ms (~31s) for the first timestamp row.
      EXPANDED + 0 rows + an ACTIVE spinner means STILL LOADING, never a block.
  R6  Extract GENERICALLY: walk the panel subtree piercing shadow roots; leaf
      elements whose text is a timestamp; walk up <=4 ancestors to the ROW. The
      old per-row custom-element selector is STALE (the current "In this video"
      panel never emits it) and is deliberately not used anywhere in this file.
  R7  Scroll to stability (up to ~90 passes so an 86-minute webinar completes),
      de-duplicating on f"{start}|{text}".
  R8  Output: [{"start": <int seconds>, "text": "<str>"}] - the cache contract
      (data/transcript_<id>.json).

## Named failures (never a bare "blocked")

  F1  chrome_session.ChromeProfileLockedError - no debug port. Never degrades.
  F2  NoTranscriptAvailable - panel/control present, 0 rows after the FULL wait
      and no active spinner: that video has no transcript. NOT "blocked".
  F3  TranscriptStillLoading - 0 rows while a spinner is still active. We keep
      waiting (extra rounds); only a hard cap ends it, and it is reported as
      "still loading", never as a block.

D6: one video at a time, normal page loads, no bulk loop. fetch_many walks its
ids sequentially on ONE attached driver.

Importable:
  fetch_transcript_panel(video_id)  -> [{"start","text"}]   (RAISES F1/F2/F3)
  fetch_segments(video_id)          -> [{"start","text"}]   ([] on F2/F3; raises F1)
  fetch_many(ids)                   -> {id: [segments]}     (same rules)
  read_panel(driver)                -> the recipe on a driver already on a watch page

CLI:
  python panel_transcript.py <id|url> [--json OUT]
  python panel_transcript.py --ids ID1 ID2 ... [--json OUT]
"""
import sys, os, re, json, time, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chrome_session
from chrome_session import ChromeProfileLockedError  # F1 (re-exported)


# ---------------------------------------------------------------------------
# Named failures F2 / F3 (F1 lives in chrome_session)
# ---------------------------------------------------------------------------
class NoTranscriptAvailable(RuntimeError):
    """F2. The video has no transcript (no control, or panel present with 0 rows
    after the full wait and no active spinner). Report "no transcript
    available" - NOT "blocked"."""


class TranscriptStillLoading(RuntimeError):
    """F3 exhausted. 0 rows while a spinner was still active through every wait
    round. The panel is STILL LOADING - this is not a block and not "no
    transcript"; retry later on a slower page."""


# ---------------------------------------------------------------------------
# Recipe constants (R1-R7). Tests assert on these numbers.
# ---------------------------------------------------------------------------
EXPAND_WAIT_S = 0.4          # R1
OPEN_POLLS = 10              # R2: wait for the watch page to render the control
OPEN_POLL_S = 1.0
PANEL_POLLS = 10             # R3: wait for the panel element after the click
PANEL_POLL_S = 0.5
TAB_POLLS = 6                # R4: the tabs render a beat after the panel opens
TAB_POLL_S = 0.5
SPINNER_POLLS = 14           # R5: 14 x 2200ms = 30.8s before declaring failure
SPINNER_POLL_S = 2.2
SPINNER_EXTRA_ROUNDS = 2     # F3: keep waiting while a spinner is active (hard cap)
SCROLL_SLEEP_S = 0.2         # R7: 170-240ms
SCROLL_STABLE_PASSES = 4     # R7: stop after 3-5 consecutive no-new passes
SCROLL_MAX_PASSES = 90       # R7: enough for an 86-minute webinar


# ---------------------------------------------------------------------------
# In-page JS. Every script is a plain string run via driver.execute_script, so
# the whole recipe is inspectable offline (tests assert on these strings).
# ---------------------------------------------------------------------------
JS_PANEL_SELECTOR = ('ytd-engagement-panel-section-list-renderer'
                     '[target-id="engagement-panel-searchable-transcript"]')   # R3

# Shared helpers, prepended to every panel script. deepWalk PIERCES shadow roots.
_JS_PRELUDE = r"""
const PANEL_SEL = '%s';
const TS = /^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$/;
function getPanel() { return document.querySelector(PANEL_SEL); }
function parentOf(el) {
  return el.parentElement || (el.getRootNode && el.getRootNode().host) || null;
}
function deepWalk(root, fn) {
  const stack = [root];
  while (stack.length) {
    const el = stack.pop();
    fn(el);
    const kids = Array.from(el.children || []);
    if (el.shadowRoot) kids.push.apply(kids, Array.from(el.shadowRoot.children));
    for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
  }
}
function collectRows(panel) {
  const rows = [];
  deepWalk(panel, function (el) {
    if (el.children.length !== 0) return;                 // LEAF elements only
    const t = el.textContent || '';
    const m = TS.exec(t);
    if (!m) return;
    const tsText = t.trim();
    let row = null, cur = el;
    for (let i = 0; i < 4 && cur; i++) {                  // walk UP <= 4 ancestors
      cur = parentOf(cur);
      if (!cur) break;
      if (((cur.textContent || '').trim().length) > tsText.length + 2) { row = cur; break; }
    }
    if (!row) return;
    const text = (row.textContent || '').replace(/\s+/g, ' ').trim()
                   .replace(/^\d{1,2}:\d{2}(:\d{2})?\s*/, '');
    if (!text) return;                                    // skip empty rows
    const start = (m[3] !== undefined)
      ? (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3])
      : (+m[1]) * 60 + (+m[2]);
    rows.push([start, text]);
  });
  return rows;
}
""" % JS_PANEL_SELECTOR

# R1 - expand the description.
JS_EXPAND = "const e=document.querySelector('#expand'); if(e){e.click(); return true;} return false;"

# R2 - open the panel (three fallbacks, in order).
JS_OPEN_PANEL = r"""
let b = document.querySelector('button[aria-label="Show transcript"]')
     || document.querySelector('button[aria-label="Transcript"]');
if (!b) {
  b = Array.from(document.querySelectorAll('button')).find(function (x) {
    return /show transcript/i.test((x.textContent || '') + ' ' + (x.getAttribute('aria-label') || ''));
  }) || null;
}
if (b) { b.click(); return true; }
return false;
"""

# R3 - is the panel element in the DOM yet? (deliberately reads no rows)
JS_PANEL_PRESENT = _JS_PRELUDE + "return !!getPanel();"

# R4 - click the "Transcript" tab. The panel opens on CHAPTERS.
JS_CLICK_TRANSCRIPT_TAB = _JS_PRELUDE + r"""
const panel = getPanel();
if (!panel) return false;
const leaves = [];
deepWalk(panel, function (el) {
  if (el.children.length === 0 && (el.textContent || '').trim() === 'Transcript') leaves.push(el);
});
for (const leaf of leaves) {
  let cur = leaf;
  for (let i = 0; i <= 4 && cur; i++) {                    // the leaf itself + <=4 ancestors
    if (cur.tagName === 'BUTTON' || (cur.getAttribute && cur.getAttribute('role') === 'tab')) {
      cur.click();
      return true;
    }
    cur = parentOf(cur);
  }
}
return false;
"""

# R5 - panel state: visibility, row count, active spinner.
JS_PANEL_STATE = _JS_PRELUDE + r"""
const panel = getPanel();
if (!panel) return {present: false, visibility: null, rows: 0, spinner: false};
let spinner = false;
deepWalk(panel, function (el) {
  const tag = (el.tagName || '').toLowerCase();
  if ((tag === 'tp-yt-paper-spinner' || tag === 'tp-yt-paper-spinner-lite') && el.hasAttribute('active')) spinner = true;
  if (tag === 'yt-spinner' && el.offsetParent !== null) spinner = true;
});
return {present: true, visibility: panel.getAttribute('visibility'),
        rows: collectRows(panel).length, spinner: spinner};
"""

# R6 - generic extraction (shadow-piercing, timestamp leaves -> row ancestor).
JS_COLLECT_ROWS = _JS_PRELUDE + "const panel = getPanel(); return panel ? collectRows(panel) : [];"

# R7 - scroll the first overflowing panel descendant. arguments[0]: 'bottom' | 'top'.
JS_SCROLL = _JS_PRELUDE + r"""
const panel = getPanel();
if (!panel) return false;
let scroller = null;
deepWalk(panel, function (el) {
  if (!scroller && el.scrollHeight > el.clientHeight + 40) scroller = el;
});
if (!scroller) return false;
scroller.scrollTop = (arguments[0] === 'top') ? 0 : scroller.scrollHeight;
return true;
"""


# ---------------------------------------------------------------------------
# The recipe (driver already on a watch page)
# ---------------------------------------------------------------------------
def _log(msg):
    print(f"  [browser-panel] {msg}", flush=True)


def _state(driver):
    st = driver.execute_script(JS_PANEL_STATE) or {}
    return {"present": bool(st.get("present")), "visibility": st.get("visibility"),
            "rows": int(st.get("rows") or 0), "spinner": bool(st.get("spinner"))}


def _collect(driver):
    out = []
    for r in (driver.execute_script(JS_COLLECT_ROWS) or []):
        try:
            out.append((int(r[0]), str(r[1])))
        except Exception:
            continue
    return out


def read_panel(driver):
    """Run R1-R8 on a driver ALREADY sitting on a watch page.

    Returns [{"start": int, "text": str}] sorted by start. Raises
    NoTranscriptAvailable (F2) or TranscriptStillLoading (F3). Loads no page
    and launches nothing.
    """
    # R1 - expand description.
    driver.execute_script(JS_EXPAND)
    time.sleep(EXPAND_WAIT_S)

    # R2 - open the panel. The watch page may still be rendering its controls.
    opened = False
    for _ in range(OPEN_POLLS):
        if driver.execute_script(JS_OPEN_PANEL):
            opened = True
            break
        time.sleep(OPEN_POLL_S)
    if not opened:
        raise NoTranscriptAvailable(
            "no 'Show transcript' control on the watch page - this video has no "
            "transcript available (this is not a block)")

    # R3 - wait for the panel element itself.
    for _ in range(PANEL_POLLS):
        if driver.execute_script(JS_PANEL_PRESENT):
            break
        time.sleep(PANEL_POLL_S)

    # R4 - the panel opens on CHAPTERS: click the Transcript tab BEFORE reading.
    for _ in range(TAB_POLLS):
        if driver.execute_script(JS_CLICK_TRANSCRIPT_TAB):
            break
        time.sleep(TAB_POLL_S)

    # R5 - patient spinner wait (>=30s). F3: while a spinner is active, keep waiting.
    for round_no in range(1 + SPINNER_EXTRA_ROUNDS):
        for _ in range(SPINNER_POLLS):
            if _state(driver)["rows"] > 0:
                break
            time.sleep(SPINNER_POLL_S)
        st = _state(driver)
        if st["rows"] > 0:
            break
        if not st["spinner"]:
            raise NoTranscriptAvailable(                       # F2
                "transcript panel opened but yielded 0 rows after the full "
                f"{SPINNER_POLLS * SPINNER_POLL_S:.0f}s wait with no active spinner - "
                "no transcript available for this video (this is not a block)")
        _log(f"0 rows but a spinner is still active (round {round_no + 1}) - "
             "STILL LOADING, not a block; waiting")
    else:
        raise TranscriptStillLoading(                          # F3 hard cap
            "transcript panel is still loading (spinner active, 0 rows) after "
            f"{1 + SPINNER_EXTRA_ROUNDS} wait rounds - NOT a block; retry later")

    # R7 - scroll to stability, de-duplicating on start|text.
    seen = {}
    def merge():
        new = 0
        for start, text in _collect(driver):
            key = f"{start}|{text}"
            if key not in seen:
                seen[key] = (start, text)
                new += 1
        return new

    merge()
    stable = 0
    for _ in range(SCROLL_MAX_PASSES):
        driver.execute_script(JS_SCROLL, "bottom")
        time.sleep(SCROLL_SLEEP_S)
        if merge() == 0:
            stable += 1
            if stable >= SCROLL_STABLE_PASSES:
                break
        else:
            stable = 0
    driver.execute_script(JS_SCROLL, "top")
    time.sleep(SCROLL_SLEEP_S)
    merge()

    # R8 - the cache contract.
    return [{"start": s, "text": t}
            for s, t in sorted(seen.values(), key=lambda p: p[0])]


# ---------------------------------------------------------------------------
# Session + navigation (attach-only)
# ---------------------------------------------------------------------------
def vid_of(s):
    m = re.search(r"(?:v=|youtu\.be/|/watch\?v=)([A-Za-z0-9_-]{11})", s)
    return m.group(1) if m else (s if re.fullmatch(r"[A-Za-z0-9_-]{11}", s) else None)


def build_driver(headed=True):
    """ATTACH a Selenium driver to Gavin's already-running Chrome. NEVER launches.

    chrome_session.acquire_session() is called FIRST - before selenium is even
    imported - so a missing debug port raises F1 immediately and nothing else
    happens. The driver is then created with Options.debugger_address on the
    existing DEBUG_PORT (an attach; chromedriver is only the protocol shim).

    Returns (driver, owns_process). owns_process is always False: callers MUST
    NOT driver.quit() it, only driver.close() the tab THIS call opened.
    `headed` is accepted for signature compatibility and ignored.
    """
    _, owns_process, _ = chrome_session.acquire_session()          # F1 raised here

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    o = Options()
    o.debugger_address = f"127.0.0.1:{chrome_session.DEBUG_PORT}"
    d = webdriver.Chrome(service=Service(), options=o)
    d.set_page_load_timeout(45)
    # A NEW tab for our own work - never hijack the tab Gavin is looking at.
    d.switch_to.new_window("tab")
    return d, owns_process


def dismiss_consent(d):
    try:
        if "consent." in d.current_url:
            d.execute_script("const b=[...document.querySelectorAll('button')].find(x=>/reject all|accept all|i agree/i.test(x.textContent||x.ariaLabel||''));if(b)b.click();")
            time.sleep(2)
    except Exception:
        pass


def fetch_on(driver, video_id, timeout=40):
    """Load ONE video's normal watch page on an EXISTING attached driver and run
    the recipe. `timeout` is accepted for compatibility; the recipe's waits are
    the fixed constants above. RAISES F2/F3 (never returns a bare [])."""
    vid = vid_of(video_id)
    if not vid:
        raise NoTranscriptAvailable(f"not a YouTube video id: {video_id!r}")
    url = "https://www.youtube.com/watch?v=" + vid + "&hl=en"
    driver.get(url)
    dismiss_consent(driver)
    if "consent." in driver.current_url:
        driver.get(url)
    time.sleep(3.2)
    return read_panel(driver)


def _release(d, owns_process):
    """Ownership contract (chrome_session.py): an ATTACHED session (Gavin's live
    browser) is NEVER quit() - only the tab THIS call opened is closed."""
    try:
        if owns_process:
            d.quit()
        else:
            d.close()
    except Exception:
        pass


def fetch_transcript_panel(video_id):
    """THE entry point the ladder uses. One video, one attached driver.
    RAISES F1 (no debug port), F2 (no transcript), F3 (still loading)."""
    d, owns_process = build_driver()
    try:
        return fetch_on(d, video_id)
    finally:
        _release(d, owns_process)


def fetch_segments(video_id, headed=True, timeout=40):
    """Compatibility wrapper. [] for F2/F3 (no transcript / still loading);
    F1 still RAISES - a missing debug port is never swallowed."""
    try:
        return fetch_transcript_panel(video_id)
    except (NoTranscriptAvailable, TranscriptStillLoading) as e:
        print(f"  [browser-panel] {vid_of(video_id) or video_id}: {e}", flush=True)
        return []


def fetch_many(ids, headed=True, timeout=40):
    """Several videos, SEQUENTIALLY on ONE attached driver (D6: one at a time).
    F2/F3 yield [] for that video; F1 raises before anything is read."""
    out = {}
    d, owns_process = build_driver(headed)
    try:
        for i in ids:
            vid = vid_of(i) or i
            try:
                out[vid] = fetch_on(d, vid, timeout)
            except (NoTranscriptAvailable, TranscriptStillLoading) as e:
                print(f"  [browser-panel] {vid}: {e}", flush=True)
                out[vid] = []
    finally:
        _release(d, owns_process)
    return out


def _joined(segs):
    return re.sub(r"\s+", " ", " ".join(s["text"] for s in segs)).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--headed", action="store_true",
                     help="accepted for compatibility; a no-op - this module only "
                          "ATTACHES to your running Chrome and never launches one")
    ap.add_argument("--json", default=None)
    ap.add_argument("--timeout", type=int, default=40)
    a = ap.parse_args()
    try:
        if a.ids:
            res = fetch_many(a.ids, a.headed, a.timeout)
            payload = {vid: {"count": len(segs), "chars": len(_joined(segs)), "segments": segs, "text": _joined(segs)} for vid, segs in res.items()}
            if a.json: open(a.json, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2))
            print(json.dumps({vid: v["count"] for vid, v in payload.items()}, ensure_ascii=False))
            sys.exit(0 if any(v["count"] for v in payload.values()) else 2)
        if not a.video:
            print("ERR: give a <video> or --ids", file=sys.stderr); sys.exit(2)
        segs = fetch_segments(a.video, a.headed, a.timeout)
    except ChromeProfileLockedError as e:
        print(f"ERR (F1): {e}", file=sys.stderr); sys.exit(3)
    if not segs:
        print("ERR: no transcript read", file=sys.stderr); sys.exit(2)
    text = _joined(segs)
    res = {"id": vid_of(a.video), "count": len(segs), "chars": len(text), "segments": segs, "text": text}
    if a.json: open(a.json, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({"id": res["id"], "count": res["count"], "chars": res["chars"], "first": segs[0], "last": segs[-1]}, ensure_ascii=False))
    sys.exit(0)

if __name__ == "__main__":
    main()
