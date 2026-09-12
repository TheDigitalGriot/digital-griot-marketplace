#!/usr/bin/env python
"""panel_transcript.py -- YouTube transcript via the on-page transcript PANEL
(YouTube's internal in-browser pipeline), which survives a residential-IP flag
because it never touches the blocked timedtext endpoint.

Same DOM action every video: expand description -> Show transcript ->
read ytd-transcript-segment-renderer rows -> clean. Coded, not prompted.

Importable:
  fetch_segments(video_id, headed=False, timeout=40) -> [ {t,text}, ... ]  ([] on failure; never raises)
  fetch_many(ids, headed=False, timeout=40)          -> { id: [segments] }  (ONE reused driver)

CLI:
  python panel_transcript.py <id|url> [--headed] [--json OUT] [--timeout 40]
  python panel_transcript.py --ids ID1 ID2 ... [--json OUT]
"""
import sys, os, re, json, time, tempfile, argparse

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

def vid_of(s):
    m = re.search(r"(?:v=|youtu\.be/|/watch\?v=)([A-Za-z0-9_-]{11})", s)
    return m.group(1) if m else (s if re.fullmatch(r"[A-Za-z0-9_-]{11}", s) else None)

def build_driver(headed=False):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    o = Options()
    o.binary_location = CHROME
    if not headed:
        o.add_argument("--headless=new")
    for a in ("--window-size=1400,1000","--lang=en-US","--mute-audio","--no-first-run",
              "--no-default-browser-check","--disable-blink-features=AutomationControlled"):
        o.add_argument(a)
    o.add_argument("--user-data-dir=" + tempfile.mkdtemp(prefix="ytpanel_"))
    o.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    d = webdriver.Chrome(service=Service(), options=o)
    d.set_page_load_timeout(45)
    return d

def dismiss_consent(d):
    try:
        if "consent." in d.current_url:
            d.execute_script("const b=[...document.querySelectorAll('button')].find(x=>/reject all|accept all|i agree/i.test(x.textContent||x.ariaLabel||''));if(b)b.click();")
            time.sleep(2)
    except Exception:
        pass

def _open_transcript(d):
    d.execute_script("const e=document.querySelector('tp-yt-paper-button#expand, #expand');if(e)e.click();")
    time.sleep(1.2)
    clicked = d.execute_script("const b=[...document.querySelectorAll('button, a, yt-button-shape button, ytd-button-renderer button')].find(x=>/show transcript|transcript/i.test((x.getAttribute('aria-label')||'')+' '+(x.textContent||'')));if(b){b.click();return true;}return false;")
    if not clicked:
        d.execute_script("const k=document.querySelector('#button-shape button[aria-label*=\"More actions\" i], ytd-menu-renderer button[aria-label*=\"More\" i]');if(k)k.click();")
        time.sleep(1.0)
        clicked = d.execute_script("const mi=[...document.querySelectorAll('tp-yt-paper-item, ytd-menu-service-item-renderer, yt-formatted-string')].find(x=>/show transcript/i.test(x.textContent||''));if(mi){mi.click();return true;}return false;")
    return bool(clicked)

def _read_segments(d, timeout):
    end = time.time() + timeout; last = -1
    while time.time() < end:
        n = d.execute_script("return document.querySelectorAll('ytd-transcript-segment-renderer').length;")
        if n and n == last:
            break
        last = n
        d.execute_script("const p=document.querySelector('ytd-transcript-segment-list-renderer #segments-container')||document.querySelector('ytd-transcript-segment-list-renderer');if(p)p.scrollTop=p.scrollHeight;")
        time.sleep(0.8)
    return d.execute_script("return [...document.querySelectorAll('ytd-transcript-segment-renderer')].map(s=>({t:(s.querySelector('.segment-timestamp')?.textContent||'').trim(),text:(s.querySelector('.segment-text, yt-formatted-string.segment-text')?.textContent||'').trim()})).filter(x=>x.text);")

def _clean(segs):
    seen=set(); out=[]
    for s in segs:
        k=(s["t"], s["text"])
        if k in seen: continue
        seen.add(k); out.append(s)
    return out

def fetch_on(driver, video_id, timeout=40):
    """Fetch ONE video's segments on an EXISTING driver. [] on failure."""
    vid = vid_of(video_id)
    if not vid: return []
    try:
        driver.get("https://www.youtube.com/watch?v=" + vid + "&hl=en")
        dismiss_consent(driver)
        if "consent." in driver.current_url:
            driver.get("https://www.youtube.com/watch?v=" + vid + "&hl=en")
        time.sleep(3.2)
        if not _open_transcript(driver):
            return []
        time.sleep(1.3)
        return _clean(_read_segments(driver, timeout))
    except Exception as e:
        print(f"  [selenium-panel] {vid}: {type(e).__name__}: {e}", flush=True)
        return []

def fetch_segments(video_id, headed=False, timeout=40):
    """Fetch ONE video with its own driver. [] on failure; never raises."""
    try:
        d = build_driver(headed)
    except Exception as e:
        print(f"  [selenium-panel] driver unavailable: {type(e).__name__}: {e}", flush=True)
        return []
    try:
        return fetch_on(d, video_id, timeout)
    finally:
        try: d.quit()
        except Exception: pass

def fetch_many(ids, headed=False, timeout=40):
    """Fetch several videos reusing ONE driver."""
    out = {}
    try:
        d = build_driver(headed)
    except Exception as e:
        print(f"  [selenium-panel] driver unavailable: {type(e).__name__}: {e}", flush=True)
        return {vid_of(i) or i: [] for i in ids}
    try:
        for i in ids:
            vid = vid_of(i) or i
            out[vid] = fetch_on(d, vid, timeout)
    finally:
        try: d.quit()
        except Exception: pass
    return out

def _joined(segs):
    return re.sub(r"\s+", " ", " ".join(s["text"] for s in segs)).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--json", default=None)
    ap.add_argument("--timeout", type=int, default=40)
    a = ap.parse_args()
    if a.ids:
        res = fetch_many(a.ids, a.headed, a.timeout)
        payload = {vid: {"count": len(segs), "chars": len(_joined(segs)), "segments": segs, "text": _joined(segs)} for vid, segs in res.items()}
        if a.json: open(a.json, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2))
        print(json.dumps({vid: v["count"] for vid, v in payload.items()}, ensure_ascii=False))
        sys.exit(0 if any(v["count"] for v in payload.values()) else 2)
    if not a.video:
        print("ERR: give a <video> or --ids", file=sys.stderr); sys.exit(2)
    segs = fetch_segments(a.video, a.headed, a.timeout)
    if not segs:
        print("ERR: no transcript read", file=sys.stderr); sys.exit(2)
    text = _joined(segs)
    res = {"id": vid_of(a.video), "count": len(segs), "chars": len(text), "segments": segs, "text": text}
    if a.json: open(a.json, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({"id": res["id"], "count": res["count"], "chars": res["chars"], "first": segs[0], "last": segs[-1]}, ensure_ascii=False))
    sys.exit(0)

if __name__ == "__main__":
    main()