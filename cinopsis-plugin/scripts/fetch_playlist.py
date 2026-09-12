#!/usr/bin/env python3
"""Surface newly-added videos from a YouTube playlist (id-based seen-diff).

A playlist URL (`youtube.com/playlist?list=<ID>`) is the same flat-playlist
primitive `fetch_videos.py` already uses for channels — a different tab. But
where the channel path bounds itself with `--days`, a playlist has no recency
filter, so "new" is defined purely by a **seen-diff**: an id not in the local
manifest is new.

First sight of a playlist would otherwise treat every entry as new (a mass dump
into the pipeline). Instead the default SEEDS the baseline from videos already
processed anywhere — cached transcripts (`transcript_<id>.json`) plus video ids
in existing comparison sessions — so the first run surfaces only the
uncatalogued gap. `--all` forces the full list; `--seed` seeds-and-exits.

State/config split (mirrors the rest of cinopsis):
  - data/playlists.json   -> checked-in config (CLAUDE_PLUGIN_ROOT/data), like channels.json
  - playlist_seen.json    -> mutable state (DATA_DIR), like fetch_progress.json

No auto-chaining: the surfaced ids are PRINTED with the two handoff commands
(fetch_transcripts.py --ids ... --chunk N ; compare_videos.py --urls ... --from-cache),
matching the pinned batch recipe in SKILL.md.

Usage:
    python fetch_playlist.py <url|list_id>              # surface new (seed on first sight)
    python fetch_playlist.py --name "My Playlist"       # resolve from data/playlists.json
    python fetch_playlist.py <url> --all                # surface the full list, ignore the manifest
    python fetch_playlist.py <url> --seed               # seed the manifest and exit (surface nothing)
    python fetch_playlist.py <url> --playlist-end 200   # cap the flat-playlist scan
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from _utils import find_ytdlp, get_env, DATA_DIR, canonical_data_dir, resolve_cookies

PLAYLISTS_FILE = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).parent.parent)) / "data" / "playlists.json"
SEEN_FILE = DATA_DIR / "playlist_seen.json"
DEFAULT_MAX_NEW = int(os.environ.get("CINOPSIS_MAX_NEW_PER_RUN", "12"))


def log(msg):
    """Progress line. Under the MCP server this is redirected stdout -> stderr."""
    print(msg, flush=True)


def parse_list_id(ref):
    """Extract a playlist id from a bare id, a playlist?list=... URL, or a watch?v=...&list=... URL."""
    ref = (ref or "").strip()
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", ref)
    if m:
        return m.group(1)
    # Bare playlist id (no URL scaffolding).
    if re.fullmatch(r"[A-Za-z0-9_-]+", ref):
        return ref
    # Last resort: hand it back untouched and let yt-dlp fail with a clear error.
    return ref


def load_playlists():
    """Read data/playlists.json -> the playlists array ([] if missing). Mirrors load_channels()."""
    if not PLAYLISTS_FILE.exists():
        return []
    with open(PLAYLISTS_FILE, encoding="utf-8") as f:
        return json.load(f).get("playlists", [])




def fetch_playlist_entries(list_id, playlist_end=None, cookies=None):
    """Flat-playlist dump of a playlist. Returns [{id, title, url}], falsy ids filtered.

    Copies the channel path's flat-playlist call (fetch_videos.fetch_channel_videos)
    but DROPS --days/upload_date filtering and does NOT hard-code --playlist-end
    (position != recency in a playlist). Private/Deleted entries carry null ids and
    are dropped before diffing. A resolved cookies.txt (see resolve_cookies) is
    threaded in as --cookies so PRIVATE/unlisted playlists resolve.
    """
    url = f"https://www.youtube.com/playlist?list={list_id}"
    cmd = [find_ytdlp(), "--flat-playlist", "--dump-json"]
    if cookies:
        cmd += ["--cookies", cookies]
    if playlist_end:
        cmd += ["--playlist-end", str(playlist_end)]
    cmd.append(url)

    # Anti-hammer gate (shared chokepoint): refuse WITHOUT touching the network
    # while a cooldown is active; else enforce minimum spacing between calls.
    try:
        import ratelimit
    except Exception:
        ratelimit = None
    if ratelimit is not None:
        try:
            ratelimit.check_gate("playlist")
        except ratelimit.RateLimited as e:
            log(f"  {e}")
            return []

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=get_env(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        log(f"  Timeout fetching playlist {list_id}")
        return []
    except Exception as e:
        log(f"  Error fetching playlist {list_id}: {e}")
        return []

    if ratelimit is not None:
        if result.returncode != 0:
            ratelimit.record_outcome(False, (result.stderr or "")[:200])
        else:
            ratelimit.record_outcome(True)

    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        vid = v.get("id")
        if not vid:  # [Private video] / [Deleted video] carry null/absent ids
            continue
        entries.append({
            "id": vid,
            "title": v.get("title") or "",
            "url": f"https://www.youtube.com/watch?v={vid}",
        })

    if playlist_end and len(entries) >= playlist_end:
        log(f"  [cap] --playlist-end {playlist_end} applied; entries beyond position "
            f"{playlist_end} were NOT fetched (no silent truncation).")
    return entries


def _session_video_ids(sessions_dir):
    """Collect video ids from every comparison_data.json under a sessions dir."""
    ids = set()
    if not sessions_dir.exists():
        return ids
    for data_file in sessions_dir.glob("*/comparison_data.json"):
        try:
            data = json.loads(data_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for video in data.get("videos", []):
            vid = video.get("id")
            if vid:
                ids.add(vid)
    return ids


def seed_from_catalog():
    """Ids of videos already processed anywhere: cached transcripts + comparison sessions.

    Used as the first-run baseline so a playlist's first sight surfaces only the
    uncatalogued gap instead of every entry.
    """
    ids = set()
    # Cached transcripts: transcript_<id>.json in DATA_DIR.
    if DATA_DIR.exists():
        for f in DATA_DIR.glob("transcript_*.json"):
            vid = f.stem[len("transcript_"):]
            if vid:
                ids.add(vid)
    # Comparison sessions: DATA_DIR/sessions plus the shared canonical dir.
    ids |= _session_video_ids(DATA_DIR / "sessions")
    ids |= _session_video_ids(canonical_data_dir() / "sessions")
    return ids


def private_playlist_hint(list_id):
    """One-liner shown when a playlist returns 0 entries and no cookies were available.

    yt-dlp exits 0 with "playlist does not exist" on a PRIVATE/unlisted playlist it
    cannot see unauthenticated, so 0 entries is the tell. Points at both fixes:
    an exported cookies.txt, or the agent-side Chrome scrape.
    """
    return (
        f"[hint] Playlist {list_id} returned 0 entries. If it is PRIVATE or unlisted, "
        "yt-dlp needs your login. Export a cookies.txt from the logged-in browser "
        "(the 'Get cookies.txt LOCALLY' Chrome extension), then pass --cookies <path> "
        f"(or set $CINOPSIS_COOKIES, or drop it at {DATA_DIR / 'cookies.txt'}). "
        "Alternatively, use the agent-side Chrome scrape to pull the list interactively."
    )


def diff_new(entries, seen_ids):
    """Entries whose id is not in seen_ids (order preserved)."""
    seen = set(seen_ids)
    return [e for e in entries if e["id"] not in seen]


def load_seen():
    """Read the whole playlist_seen.json manifest ({} if missing/corrupt)."""
    if not SEEN_FILE.exists():
        return {}
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_seen(manifest):
    """Full read-modify-write rewrite of playlist_seen.json (mirrors fetch_progress.json)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_playlist_new(ref=None, name=None, *, playlist_end=None, force_all=False,
                       seed_only=False, cookies=None, max_new=None):
    """Resolve -> fetch -> diff -> persist. The single orchestrator both the CLI and MCP tool call.

    Returns a result dict: {list_id, total_entries, new, new_ids, first_run,
    seeded_only, seeded, cookies_used}. Raises ValueError on an unresolvable reference.
    """
    if name and not ref:
        match = next((p for p in load_playlists() if p.get("name") == name), None)
        if not match:
            raise ValueError(f"No playlist named {name!r} in data/playlists.json")
        ref = match.get("url_or_id")
    if not ref:
        raise ValueError("Provide a playlist url/id or a --name from data/playlists.json")

    list_id = parse_list_id(ref)
    cookies_path = resolve_cookies(cookies)
    entries = fetch_playlist_entries(list_id, playlist_end, cookies=cookies_path)
    all_ids = [e["id"] for e in entries]

    manifest = load_seen()
    first_run = list_id not in manifest
    prior = set(manifest.get(list_id, []))

    if seed_only:
        manifest[list_id] = sorted(prior | set(all_ids))
        save_seen(manifest)
        return {
            "list_id": list_id, "total_entries": len(entries),
            "new": [], "new_ids": [], "first_run": first_run,
            "seeded_only": True, "seeded": len(all_ids),
            "cookies_used": bool(cookies_path),
        }

    if force_all:
        baseline = set()
    elif first_run:
        baseline = seed_from_catalog()
    else:
        baseline = prior

    new = diff_new(entries, baseline)

    # PACING: surface at most `cap` net-new per run so a big backlog drains a
    # bounded batch at a time instead of dumping all-N into the fetch pipeline
    # (the channel path is bounded by --playlist-end 10; this is its equivalent).
    # --all remains the explicit un-paced escape.
    cap = None if force_all else (max_new if max_new is not None else DEFAULT_MAX_NEW)
    surfaced = new[:cap] if (cap and cap > 0) else new
    remaining = len(new) - len(surfaced)

    # Mark as seen ONLY: prior + already-processed baseline present in this list +
    # the ids actually surfaced this run. The un-surfaced backlog stays unseen so
    # it resurfaces next run and drains ~cap/run -- never bulk.
    seen_now = set(prior) | (set(baseline) & set(all_ids)) | {e["id"] for e in surfaced}
    manifest[list_id] = sorted(seen_now)
    save_seen(manifest)

    return {
        "list_id": list_id, "total_entries": len(entries),
        "new": surfaced, "new_ids": [e["id"] for e in surfaced],
        "backlog_new": len(new), "remaining": remaining, "cap": cap,
        "first_run": first_run, "seeded_only": False, "seeded": 0,
        "cookies_used": bool(cookies_path),
    }


def main():
    ap = argparse.ArgumentParser(description="Surface newly-added videos from a YouTube playlist")
    ap.add_argument("ref", nargs="?", default=None,
                    help="Playlist URL or bare list id (or use --name)")
    ap.add_argument("--url", dest="url", default=None, help="Playlist URL or bare list id")
    ap.add_argument("--name", default=None, help="Named playlist from data/playlists.json")
    ap.add_argument("--playlist-end", type=int, default=None,
                    help="Cap the flat-playlist scan at N entries (logged when applied)")
    ap.add_argument("--all", action="store_true",
                    help="Force the full list — ignore the seen manifest")
    ap.add_argument("--seed", action="store_true",
                    help="Seed the manifest from the current playlist and exit (surface nothing)")
    ap.add_argument("--max-new", type=int, default=None,
                    help="Surface at most N net-new per run (default 12; env "
                         "CINOPSIS_MAX_NEW_PER_RUN). The backlog drains ~N/run -- never bulk.")
    ap.add_argument("--cookies", default=None,
                    help="Path to a cookies.txt (Netscape format) so PRIVATE/unlisted playlists "
                         "resolve. Falls back to $CINOPSIS_COOKIES, then data/cookies.txt if present.")
    args = ap.parse_args()

    ref = args.ref or args.url
    try:
        result = fetch_playlist_new(
            ref=ref, name=args.name,
            playlist_end=args.playlist_end,
            force_all=args.all, seed_only=args.seed,
            cookies=args.cookies, max_new=args.max_new,
        )
    except ValueError as e:
        print(f"Error: {e}")
        return

    list_id = result["list_id"]

    # A private/unlisted playlist yt-dlp cannot see comes back empty — surface the fix.
    if result["total_entries"] == 0 and not result["cookies_used"]:
        print("\n" + private_playlist_hint(list_id))

    if result["seeded_only"]:
        print(f"\nSeeded {result['seeded']} id(s) for playlist {list_id}. Nothing surfaced.")
        return

    new_ids = result["new_ids"]
    if not new_ids:
        seeded_note = " (first sight — baseline seeded from already-processed videos)" if result["first_run"] else ""
        print(f"\nNo new videos in playlist {list_id} — {result['total_entries']} entr(ies) checked{seeded_note}.")
        return

    print(f"\n{len(new_ids)} new video(s) surfaced from playlist {list_id} "
          f"({result['total_entries']} entr(ies) checked):")
    for i, v in enumerate(result["new"], 1):
        print(f"  {i}. {v['title']} | {v['url']}")

    remaining = result.get("remaining", 0)
    if remaining:
        print(f"\n[pace] {remaining} more net-new held back this run "
              f"(cap {result.get('cap')}/run). They surface next run -- the backlog drains a "
              f"bounded batch at a time, never in bulk. Use --all to override (not advised).")

    ids = " ".join(new_ids)
    print("\nNext — fetch transcripts (resumable, chunked):")
    print(f"  python fetch_transcripts.py --ids {ids} --chunk 5")
    print("Then — assemble a comparison from cache:")
    print(f"  python compare_videos.py --urls {ids} --from-cache")


if __name__ == "__main__":
    main()
