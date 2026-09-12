#!/usr/bin/env python3
"""
export_yt_cookies.py - first-party YouTube cookie exporter for Cinopsis.

Launches a DEDICATED Chrome profile (never your everyday GB profile), lets Chrome
serve its own already-decrypted cookies over the DevTools protocol, filters to
Google/YouTube, and writes a Netscape cookies.txt to every path Cinopsis actually
reads -- see _utils.cookie_targets() / _utils.resolve_cookies(). Nothing is
hardcoded: the jar follows $CLAUDE_PLUGIN_DATA and $CINOPSIS_COOKIES, and the
dedicated Chrome profile lives under the canonical plugin data dir.

No app-bound-encryption decryption, no admin, no process injection, no third-party
extension. Chrome hands the cookies over itself, so ABE is never fought. A
non-default --user-data-dir also sidesteps the Chrome 136+ block on debugging the
default profile.

Usage:
  python export_yt_cookies.py --login   # first time / when signed out: opens a
                                         # visible window; sign into YouTube, then
                                         # press Enter and it saves the jar.
  python export_yt_cookies.py           # later refreshes: headless and silent.
  python export_yt_cookies.py --show-paths  # print resolved paths only; no launch.

The dedicated profile stays logged in, so after the one-time --login you just run
it with no flags whenever the jar needs refreshing.
"""
import argparse, json, os, shutil, subprocess, sys, time
from urllib.request import urlopen

import websocket  # websocket-client (already installed)

from _utils import canonical_data_dir, cookie_targets

# The dedicated Chrome profile lives in the plugin's persistent data dir -- never in
# the repo (a plugin update replaces it) and never the everyday browser profile.
PROFILE_DIR = str(canonical_data_dir() / "yt-profile")
DEBUG_PORT  = int(os.environ.get("CINOPSIS_COOKIE_PORT", "9222"))
AUTH_MARKERS = {"SID", "HSID", "SSID", "APISID", "SAPISID",
                "__Secure-1PSID", "__Secure-3PSID",
                "__Secure-1PAPISID", "__Secure-3PAPISID", "LOGIN_INFO"}


def chrome_candidates():
    """Chrome executables to try, most-likely first. Discovery only -- not a plugin path.

    Covers Windows (per-machine AND per-user installs -- %LOCALAPPDATA% is where
    Chrome lands without admin), macOS and Linux, plus a $CINOPSIS_CHROME override
    and a PATH lookup, so this is not Windows-only or user-specific.
    """
    env = os.environ.get("CINOPSIS_CHROME")
    if env:
        return [env]
    cands = []
    if sys.platform == "win32":
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    elif sys.platform == "darwin":
        cands.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        cands += ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]
    for name in ("chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            cands.append(found)
    return cands

def find_chrome():
    for p in chrome_candidates():
        if os.path.exists(p):
            return p
    sys.exit("Chrome not found in the standard locations; set $CINOPSIS_CHROME to "
             "the chrome executable and re-run.")

def launch_chrome(chrome, headless):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    args = [chrome,
            "--user-data-dir=" + PROFILE_DIR,
            "--remote-debugging-port=" + str(DEBUG_PORT),
            "--remote-allow-origins=*",
            "--no-first-run", "--no-default-browser-check"]
    if headless:
        args += ["--headless=new", "--window-size=1200,900"]
    else:
        args += ["--new-window", "https://www.youtube.com"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def browser_ws_url(timeout=25):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urlopen("http://127.0.0.1:%d/json/version" % DEBUG_PORT, timeout=2) as r:
                return json.load(r)["webSocketDebuggerUrl"]
        except Exception as e:
            last = e
            time.sleep(0.5)
    sys.exit("Chrome DevTools endpoint never came up on port %d: %s" % (DEBUG_PORT, last))

def get_all_cookies(ws_url):
    ws = websocket.create_connection(ws_url)
    try:
        ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                if "error" in msg:
                    sys.exit("Storage.getCookies error: %s" % msg["error"])
                return msg["result"]["cookies"]
    finally:
        ws.close()

def keep(c):
    d = c["domain"].lstrip(".").lower()
    return d.endswith("youtube.com") or d.endswith("google.com") or d.endswith("googlevideo.com")

def to_netscape(cookies):
    lines = ["# Netscape HTTP Cookie File",
             "# Exported by Cinopsis export_yt_cookies.py - keep private.", ""]
    for c in cookies:
        dom = c["domain"]
        incl = "TRUE" if dom.startswith(".") else "FALSE"
        secure = "TRUE" if c.get("secure") else "FALSE"
        exp = c.get("expires", -1)
        expiry = int(exp) if exp and exp > 0 else 0
        prefix = "#HttpOnly_" if c.get("httpOnly") else ""
        lines.append("\t".join([prefix + dom, incl, c.get("path", "/"),
                                secure, str(expiry), c["name"], c["value"]]))
    return "\n".join(lines) + "\n"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true",
                    help="open a visible window to sign in, then save the jar.")
    ap.add_argument("--port", type=int, default=DEBUG_PORT,
                    help="Chrome remote-debugging port ($CINOPSIS_COOKIE_PORT, default 9222).")
    ap.add_argument("--show-paths", action="store_true",
                    help="print the resolved profile dir + cookie-jar targets, then exit. "
                         "Launches nothing and touches the network not at all.")
    args = ap.parse_args()
    globals()["DEBUG_PORT"] = args.port

    if args.show_paths:
        print("profile dir : %s" % PROFILE_DIR)
        for out in cookie_targets():
            print("cookie jar  : %s" % out)
        return

    chrome = find_chrome()
    proc = launch_chrome(chrome, headless=not args.login)
    try:
        ws_url = browser_ws_url()
        if args.login:
            print("A Chrome window opened. Sign into YouTube in it, then come back")
            input("here and press Enter to save the cookie jar... ")
        cookies = [c for c in get_all_cookies(ws_url) if keep(c)]
    finally:
        proc.terminate()
        try: proc.wait(timeout=10)
        except Exception: proc.kill()

    auth = sorted(n for n in {c["name"] for c in cookies} if n in AUTH_MARKERS)
    jar = to_netscape(cookies)
    for out in cookie_targets():
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(jar)
        print("wrote %d cookies -> %s" % (len(cookies), out))
    if auth:
        print("auth cookies present: " + ", ".join(auth))
    else:
        print("WARNING: no authenticated Google cookies found.")
        print("Run:  python export_yt_cookies.py --login   and sign in first.")

if __name__ == "__main__":
    main()
