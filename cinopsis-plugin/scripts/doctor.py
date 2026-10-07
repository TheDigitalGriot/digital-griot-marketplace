#!/usr/bin/env python3
"""doctor.py - Cinopsis health check, built on Agent-Reach's doctor.

Agent-Reach's model, lifted raw (scripts/reach): every transcript source is a
Channel whose check() really EXECUTES what it needs (reach.probe - shutil.which
is not proof), and the doctor just collects the results (reach.doctor.check_all
/ format_report). Cinopsis registers its five transcript sources plus Agent-Reach's
YouTube channel, so one report covers the whole acquisition layer, and prints
the live source order and where it came from.

    python scripts/doctor.py              # report (offline: no request leaves this machine)
    python scripts/doctor.py --json       # machine-readable
    python scripts/doctor.py --live       # + at most ONE lightweight request per network source, gated
    python scripts/doctor.py --watch      # quiet scheduled-task form (Agent-Reach `watch`)
    python scripts/doctor.py --check-update

The CLI helpers below (UTF-8 console, doctor / watch / update check) are lifted
from Agent-Reach's cli.py; seams point them at Cinopsis's version and repo.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sources  # noqa: E402,F401 - registers the transcript sources as Agent-Reach channels

CINOPSIS_GITHUB_API = "https://api.github.com/repos/TheDigitalGriot/cinopsis"
PLUGIN_JSON = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"


def cinopsis_version() -> str:
    try:
        return json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]
    except Exception:
        return "0.0.0"

# >>> LIFT agent-reach@a19a171f agent_reach/cli.py:42-57
def _ensure_utf8_console():
    """Best-effort Windows console UTF-8 setup for CLI runtime only."""
    if sys.platform != "win32":
        return
    # Avoid interfering with pytest/captured streams.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        import io
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        # Do not crash CLI just because encoding patch failed.
        pass
# <<< LIFT

# >>> LIFT agent-reach@a19a171f agent_reach/cli.py:2021-2037
def _cmd_doctor(args=None):
    from reach.config import Config  # seam: package import
    from reach.doctor import check_all, format_report  # seam: package import
    config = Config(read_only=True)
    results = check_all(config)

    if args is not None and getattr(args, "json", False):
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    report = format_report(results)
    try:
        from rich import print as rich_print
    except ImportError:
        print(report)
    else:
        rich_print(report)
# <<< LIFT

# >>> LIFT agent-reach@a19a171f agent_reach/cli.py:2151-2395
def _classify_update_error(exc):
    """Classify update-check errors for user-friendly diagnostics."""
    import requests

    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        msg = str(exc).lower()
        dns_markers = [
            "name or service not known",
            "temporary failure in name resolution",
            "nodename nor servname",
            "getaddrinfo failed",
            "name resolution",
            "dns",
        ]
        if any(marker in msg for marker in dns_markers):
            return "dns"
        return "connection"
    if isinstance(exc, requests.exceptions.HTTPError):
        return "http"
    return "unknown"


def _update_error_text(kind):
    """Map internal error kinds to user-facing text."""
    mapping = {
        "timeout": "network timeout",  # seam: English UI
        "dns": "DNS resolution failed",  # seam: English UI
        "rate_limit": "GitHub API rate limit",  # seam: English UI
        "connection": "network connection failed",  # seam: English UI
        "server_error": "GitHub is temporarily unavailable",  # seam: English UI
        "http": "HTTP request failed",  # seam: English UI
        "unknown": "unknown network error",  # seam: English UI
    }
    return mapping.get(kind, "request failed")  # seam: English UI


def _classify_github_response_error(resp):
    """Classify non-200 GitHub responses that merit special handling."""
    if resp is None:
        return "unknown"
    if resp.status_code == 429:
        return "rate_limit"
    if resp.status_code == 403:
        remaining = resp.headers.get("X-RateLimit-Remaining", "")
        if remaining == "0":
            return "rate_limit"
        try:
            message = resp.json().get("message", "").lower()
            if "rate limit" in message:
                return "rate_limit"
        except Exception:
            pass
    if 500 <= resp.status_code < 600:
        return "server_error"
    return None


def _github_get_with_retry(url, timeout=10, retries=3, sleeper=time.sleep):
    """GET GitHub API with retry/backoff and basic error classification."""
    import requests

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            if attempt >= retries:
                return None, _classify_update_error(exc), attempt
            sleeper(2 ** (attempt - 1))
            continue

        err_kind = _classify_github_response_error(resp)
        if err_kind in ("rate_limit", "server_error"):
            if attempt >= retries:
                return None, err_kind, attempt
            delay = 2 ** (attempt - 1)
            retry_after = resp.headers.get("Retry-After")
            if err_kind == "rate_limit" and retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except Exception:
                    pass
            sleeper(delay)
            continue

        return resp, None, attempt

    return None, "unknown", retries


#: Full update = package + upstream tools + skill. The one-liner walks an
#: agent through all three (docs/update.md); bare pip only updates the package.
_UPDATE_INSTRUCTIONS = (
    "Update Cinopsis (plugin + skills) from Claude Code:\n"  # seam: Cinopsis update path
    "  claude plugin update cinopsis@digital-griot-marketplace\n"  # seam: Cinopsis update path
    "Or pull the repo directly:\n"  # seam: Cinopsis update path
    "  git -C <cinopsis checkout> pull --ff-only"  # seam: Cinopsis update path
)


def _is_newer_version(remote: str, local: str) -> bool:
    """True if remote is strictly newer than local (semantic compare).

    A plain != would tell users "update available" when their local build is
    AHEAD of the latest release (e.g. installed from main during a release
    window) — and walk them into a downgrade.
    """
    def parse(v):
        try:
            return tuple(int(x) for x in v.strip().split("."))
        except ValueError:
            return None

    remote_version, local_version = parse(remote), parse(local)
    if remote_version is None or local_version is None:
        return remote != local  # unparseable — fall back to old behavior
    return remote_version > local_version


def _cmd_check_update():
    """Check for newer versions on GitHub."""
    __version__ = cinopsis_version()  # seam: Cinopsis version from plugin.json

    print(f"Current version: v{__version__}")  # seam: English UI
    release_url = f"{CINOPSIS_GITHUB_API}/releases/latest"  # seam: Cinopsis repo
    commit_url = f"{CINOPSIS_GITHUB_API}/commits/main"  # seam: Cinopsis repo

    # Fetch latest release with retry/backoff.
    resp, err, attempts = _github_get_with_retry(release_url, timeout=10, retries=3)
    if err:
        print(f"[!] Cannot check for updates ({_update_error_text(err)}, tried {attempts} times)")  # seam: English UI
        return "error"

    if resp.status_code == 200:
        data = resp.json()
        latest = data.get("tag_name", "").lstrip("v")
        body = data.get("body", "")

        if latest and _is_newer_version(latest, __version__):
            print(f"Latest version: v{latest} <- update available")  # seam: English UI
            if body:
                print()
                print("Release notes:")  # seam: English UI
                # Show first 20 lines of release notes
                for line in body.strip().split("\n")[:20]:
                    print(f"  {line}")
            print()
            print(_UPDATE_INSTRUCTIONS)
            return "update_available"
        print("OK - up to date")  # seam: English UI
        return "up_to_date"

    release_err = _classify_github_response_error(resp)
    if release_err == "rate_limit":
        print("[!] Cannot check for updates (GitHub API rate limit; retry later)")  # seam: English UI
        return "error"

    # No releases yet, fall back to latest main commit.
    resp2, err2, attempts2 = _github_get_with_retry(commit_url, timeout=10, retries=2)
    if err2:
        print(f"[!] Cannot check for updates ({_update_error_text(err2)}, tried {attempts + attempts2} times)")  # seam: English UI
        return "error"
    if resp2.status_code == 200:
        commit = resp2.json()
        sha = commit.get("sha", "")[:7]
        msg = commit.get("commit", {}).get("message", "").split("\n")[0]
        date = commit.get("commit", {}).get("committer", {}).get("date", "")[:10]
        print(f"Latest commit: {sha} ({date}) {msg}")  # seam: English UI
        print()
        print(_UPDATE_INSTRUCTIONS)
        return "unknown"

    commit_err = _classify_github_response_error(resp2)
    if commit_err == "rate_limit":
        print("[!] Cannot check for updates (GitHub API rate limit; retry later)")  # seam: English UI
        return "error"

    print(f"[!] Cannot check for updates (GitHub returned {resp2.status_code})")  # seam: English UI
    return "error"


def _cmd_watch():
    """Quick health check + update check, designed for scheduled tasks.

    Only outputs problems. If everything is fine, outputs a single line.
    """
    __version__ = cinopsis_version()  # seam: Cinopsis version from plugin.json
    from reach.config import Config  # seam: package import
    from reach.doctor import check_all  # seam: package import

    config = Config(read_only=True)
    issues = []

    # Check channels
    results = check_all(config)
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    total = len(results)

    # Find broken channels (were working, now broken)
    for key, r in results.items():
        if r["status"] in ("off", "error"):
            issues.append(f"[X] {r['name']}: {r['message']}")  # seam: English UI
        elif r["status"] == "warn":
            issues.append(f"[!] {r['name']}: {r['message']}")  # seam: English UI

    # Check for updates
    update_available = False
    new_version = ""
    release_body = ""
    resp, err, _attempts = _github_get_with_retry(
        f"{CINOPSIS_GITHUB_API}/releases/latest",  # seam: Cinopsis repo
        timeout=10,
        retries=2,
    )
    if not err and resp and resp.status_code == 200:
        data = resp.json()
        latest = data.get("tag_name", "").lstrip("v")
        if latest and _is_newer_version(latest, __version__):
            update_available = True
            new_version = latest
            release_body = data.get("body", "")

    # Output
    if not issues and not update_available:
        print(f"Cinopsis: all clear ({ok}/{total} sources usable, v{__version__} is current)")  # seam: English UI
        return

    print("Cinopsis doctor watch report")  # seam: English UI
    print("=" * 40)
    print(f"Version: v{__version__}  |  sources: {ok}/{total}")  # seam: English UI

    if issues:
        print()
        for issue in issues:
            print(f"  {issue}")

    if update_available:
        print()
        print(f"New version available: v{new_version}")  # seam: English UI
        if release_body:
            for line in release_body.strip().split("\n")[:10]:
                print(f"    {line}")
        print("  Update:")  # seam: English UI
        print("    claude plugin update cinopsis@digital-griot-marketplace")  # seam: Cinopsis update path
# <<< LIFT


# ---------------------------------------------------------------------------
# Cinopsis-native: the source order line and the --live probes (R3).
# ---------------------------------------------------------------------------
def source_order_line() -> str:
    order, origin = sources.resolve_order()
    return f"Transcript source order: {','.join(order)} (from {origin})"


def live_results(settings=None) -> dict:
    """At most ONE lightweight request per network source, each behind its gate.

    gemini-url probes the model resource (never a video). The YouTube-facing
    sources (og-http, local-pipeline) share ONE GET of youtube.com/generate_204
    behind the timedtext door. browser-panel is loopback-only and already
    covered by its offline check. Nothing here is recorded as a fetch outcome.
    """
    import urllib.request
    import ratelimit
    if settings is None:
        from app_settings import load_settings
        settings = load_settings()
    out = {}
    for s in sources.SOURCES:
        try:
            res = s.live_probe(settings)
        except Exception as exc:  # noqa: BLE001 - one probe must never take the report down
            res = ("error", f"probe raised {type(exc).__name__}: {exc}")
        if res:
            out[s.name] = {"status": res[0], "message": res[1]}
    try:
        ratelimit.check_gate("doctor", door="timedtext")
        with urllib.request.urlopen("https://www.youtube.com/generate_204", timeout=10) as r:
            yt = ("ok", f"youtube.com reachable (HTTP {r.status})")
    except ratelimit.RateLimited as exc:
        yt = ("warn", f"timedtext door cooling - not probed ({exc})")
    except Exception as exc:  # noqa: BLE001 - a probe reports, it never raises
        yt = ("error", f"youtube.com unreachable: {type(exc).__name__}: {exc}")
    out["youtube-reachability"] = {"status": yt[0], "message": yt[1],
                                   "covers": ["og-http", "local-pipeline"]}
    return out


def doctor_text(as_json: bool = False, live: bool = False) -> str:
    """The report as a string (the MCP tool uses this; the CLI prints it)."""
    from reach.config import Config
    from reach.doctor import check_all, format_report
    if live:
        # R10: the platform channels that probe a public API (bilibili, v2ex, xueqiu) send
        # exactly one request each, only here.
        from reach.channels import open_network_probes
        open_network_probes("once")
        try:
            results = check_all(Config(read_only=True))
        finally:
            open_network_probes("closed")  # a long-lived MCP server must not stay open after one live call
    else:
        results = check_all(Config(read_only=True))
    order, origin = sources.resolve_order()
    payload = {"version": cinopsis_version(), "source_order": list(order), "order_from": origin,
               "channels": results}
    if live:
        payload["live"] = live_results()
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = [format_report(results), "", source_order_line()]
    if live:
        lines.append("")
        lines.append("Live probes (one request each, gated):")
        for name, r in payload["live"].items():
            lines.append(f"  {name}: {r['status']} - {r['message']}")
    return "\n".join(lines)


def main() -> int:
    _ensure_utf8_console()
    ap = argparse.ArgumentParser(description="Cinopsis doctor: transcript sources and their tools")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--live", action="store_true",
                    help="Add at most one lightweight, gated request per network source")
    ap.add_argument("--watch", action="store_true", help="Quiet form for scheduled tasks")
    ap.add_argument("--check-update", action="store_true", help="Check GitHub for a newer Cinopsis")
    args = ap.parse_args()
    if args.watch:
        _cmd_watch()
        return 0
    if args.check_update:
        return 0 if _cmd_check_update() in ("up_to_date", "update_available", "unknown") else 1
    if args.live or args.json:
        text = doctor_text(as_json=args.json, live=args.live)
        if args.json:
            print(text)
        else:
            try:
                from rich import print as rich_print
                rich_print(text)
            except ImportError:
                print(text)
        return 0
    _cmd_doctor(args)
    print()
    print(source_order_line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
