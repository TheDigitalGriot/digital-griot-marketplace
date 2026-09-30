#!/usr/bin/env python3
"""READ-ONLY census of the configured playlists, with a head window that grows itself.

Answers one question -- "how deep is the unprocessed frontier in each playlist?" --
and answers it with TWO instruments, because on real lists neither one alone is
right:

  1. THE SETTLED BAND (the reliable number). Measure `unread / N` over the first N
     entries. If every entry in the window is unread the head is SATURATED and N is
     a FLOOR, not a result: it only proves the frontier is at least N deep. Double N
     and measure again, until `unread < N` or the list is exhausted. The band that
     finally comes back un-saturated is the answer, and the growth path is reported
     so the floor is never mistaken for the result. (Measured 2026-09-26: AI News
     read 25/25 at N=25 and settled at N=50 with 49 unread. A fixed window reported
     half the frontier and presented the cut as the answer.)
  2. THE CONTIGUOUS FRONTIER (labelled unreliable). The count of leading unread
     entries -- equivalently the 0-based index of the first already-processed entry.
     It stops dead at that entry, so unread entries sitting BEHIND processed ones are
     invisible to it. (Measured: 3D PixelArt contiguous 5 while 13 of the first 25
     are unread -- 8 unread entries sit behind already-processed ones.)

Neither substitutes for the other: a contiguous walk under-reports an interleaved
list, a fixed band under-reports a saturated one.

THE HEAD IS A LIST OF VIDEOS, NOT A COUNT. Every unread entry inside the settled
band is NAMED -- index, id and title -- in both the text report and --json. The
titles come free from the enumeration that already happened. And a title is a LABEL,
never an identity: every membership test, dedup and diff here runs on the id alone,
because creators run title tests and one upload answers to three names within hours.

READ-ONLY, absolutely. This never calls save_seen(), never writes the seen manifest,
never fetches a transcript, never touches a transcript door. It hashes
playlist_seen.json on entry and on exit and REFUSES to report success if the hash
moved. A census that marks things seen is not a census.

The already-processed union is built from THREE stores and never one alone: the
playlist_seen.json manifest, transcript files on disk under BOTH the repo data dir
and the canonical plugin data dir, and the video ids in every comparison session
under both sessions dirs. Each lane's count is reported, so an under-counting lane
is visible instead of silently inflating every unread number.

Network: exactly one flat-playlist enumeration per list, through the existing
fetch_playlist.fetch_playlist_entries (same cookies resolution, same rate-limit
gate). No per-video metadata calls, no transcript calls. The walk is cached to
data/_census_walk_cache.json so a re-analysis costs no second scan; --from-cache
reads it and touches the network zero times.

Usage:
    python census_playlists.py                      # census every configured playlist
    python census_playlists.py --playlist "AI News" # one list by name
    python census_playlists.py --start-n 50         # start the head window at 50
    python census_playlists.py --from-cache         # re-analyse the cached walk, no network
    python census_playlists.py --json               # machine-readable
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _utils import DATA_DIR, canonical_data_dir, resolve_cookies
from fetch_playlist import (
    _session_video_ids,
    fetch_playlist_entries,
    load_playlists,
    load_seen,
    parse_list_id,
)

SEEN_FILE = DATA_DIR / "playlist_seen.json"
CACHE_FILE = DATA_DIR / "_census_walk_cache.json"
CACHE_VERSION = 1
DEFAULT_START_N = 25
STALE_AFTER_HOURS = 24.0

CONTIGUOUS_CAVEAT = (
    "UNRELIABLE on a manually-sorted or cross-listed source: it stops at the first "
    "already-processed entry, so unread entries sitting BEHIND processed ones are "
    "invisible to it. Trust the settled band; read this one as a floor on the "
    "untouched run at the very top of the list."
)

# A blank title DECLARES itself. Parenthesised on purpose: a real YouTube title is
# never parenthesised in full, so this cannot be mistaken for one -- and it is never
# the id, because echoing an identity into a label field is the other failure mode.
TITLE_UNAVAILABLE = "(title unavailable)"


def display_title(raw):
    """The entry's title, or a DECLARED placeholder when the source gave us nothing.

    yt-dlp returns an EMPTY STRING -- not null -- for an entry whose id still
    resolves but whose metadata does not: private, deleted, or region-blocked while
    it keeps its slot in the list. Measured 2026-09-26: exactly one of 69 named
    entries across the three configured lists came back as `"title": ""`, and the
    census passed the blank straight through. The url derived correctly; only the
    title degraded, and it degraded SILENTLY.

    Silence is the defect. A blank title is indistinguishable from the id-only
    projection this named head was built to remove -- a reader cannot tell a degraded
    record from a broken pipeline. A declared placeholder is honest; a blank hides
    the very failure the field exists to expose.

    Applied where the entry dict is BUILT, once, so every consumer of
    `unread_entries` inherits it and no print site has to remember. The walk cache
    format is untouched: a cached blank still yields the placeholder at READ time, so
    `--from-cache` behaves identically and no cache rebuild is required.

    A non-blank title is returned verbatim -- not stripped, not normalised. This
    substitutes for nothing but absence.
    """
    if raw is None or not str(raw).strip():
        return TITLE_UNAVAILABLE
    return raw


def force_utf8_console():
    """Make stdout/stderr survive a YouTube title.

    Titles are arbitrary Unicode -- emoji, CJK, smart quotes -- and on Windows a bare
    console hands Python a cp1252 writer, so printing one raises UnicodeEncodeError
    and kills the run AFTER the network spend. Measured 2026-09-26: a clean census of
    2,154 entries died on U+1F92F in an AI News title. `errors="replace"` is the
    belt-and-braces rung for a stream that cannot be moved to utf-8: a glyph the
    console cannot render degrades to one character instead of aborting a report.

    This affects DISPLAY only. The walk cache and --json are written with an explicit
    utf-8 encoder, so the stored data is never lossy.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def log(msg):
    """Progress line to stderr so --json stdout stays machine-readable."""
    print(msg, file=sys.stderr, flush=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# read-only proof
# --------------------------------------------------------------------------

def manifest_fingerprint():
    """SHA-256 of playlist_seen.json, or None when it does not exist.

    Taken before and after the run. If it moves, this tool wrote seen-state, which
    is a defect -- the run reports FAILED rather than handing back numbers from a
    census that mutated what it measured.
    """
    if not SEEN_FILE.exists():
        return None
    return hashlib.sha256(SEEN_FILE.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# the already-processed union -- three stores, five lanes, each one counted
# --------------------------------------------------------------------------

def transcript_ids(directory):
    """Video ids with a transcript on disk in `directory` (both .json and .txt).

    fetch_playlist.seed_from_catalog() globs only transcript_*.json; on this machine
    the same video is often cached as .txt only, so a .json-only sweep under-counts.
    Both extensions are read here.
    """
    directory = Path(directory)
    ids = set()
    if not directory.exists():
        return ids
    for pattern in ("transcript_*.json", "transcript_*.txt"):
        for f in directory.glob(pattern):
            vid = f.stem[len("transcript_"):]
            if vid:
                ids.add(vid)
    return ids


def manifest_ids(manifest):
    """Every id in the seen manifest, across all playlists.

    A video processed under one list is processed, whichever list it is being
    counted against.
    """
    ids = set()
    for value in manifest.values():
        if isinstance(value, list):
            ids.update(v for v in value if v)
    return ids


def build_union():
    """The already-processed union plus a per-lane breakdown and loud lane warnings.

    Returns (union:set, lanes:dict[str,int], warnings:list[str]).

    The warnings are the point: a lane that comes back EMPTY while its directory
    plainly holds data is the D8(a) trap (a str handed where a Path was required
    throws internally and the lane returns an empty set). That failure has no error
    and no exit code -- it just inflates every unread number. Naming it here turns a
    silent wrong answer into a visible one.
    """
    repo_dir = Path(DATA_DIR)
    vault_dir = Path(canonical_data_dir())

    # _session_video_ids() takes a Path, NOT a str -- see the gotcha above.
    lanes_sets = {
        "manifest": manifest_ids(load_seen()),
        "transcripts_repo": transcript_ids(repo_dir),
        "transcripts_vault": transcript_ids(vault_dir),
        "sessions_repo": _session_video_ids(repo_dir / "sessions"),
        "sessions_vault": _session_video_ids(vault_dir / "sessions"),
    }

    warnings = []
    for lane, probe_dir, glob_pat in (
        ("sessions_repo", repo_dir / "sessions", "*/comparison_data.json"),
        ("sessions_vault", vault_dir / "sessions", "*/comparison_data.json"),
        ("transcripts_repo", repo_dir, "transcript_*"),
        ("transcripts_vault", vault_dir, "transcript_*"),
    ):
        if lanes_sets[lane]:
            continue
        if probe_dir.exists() and any(probe_dir.glob(glob_pat)):
            warnings.append(
                f"lane {lane} returned 0 ids while {probe_dir} holds matching files -- "
                "the union is UNDER-COUNTING and every unread number below is inflated"
            )

    union = set()
    for ids in lanes_sets.values():
        union |= ids
    lanes = {lane: len(ids) for lane, ids in lanes_sets.items()}
    return union, lanes, warnings


# --------------------------------------------------------------------------
# instrument 1 -- the head window that grows itself
# --------------------------------------------------------------------------

def measure_head(ordered_ids, union, start_n):
    """Grow the head window until it settles. Returns the settled band + growth path.

    A window is SATURATED when every entry in it is unread: the number is then a
    FLOOR on the frontier, not a measurement of it, so N doubles and we measure
    again. A window is EXHAUSTED when the list has no entries past N -- there is
    nothing left to grow into, and the band covers the whole list.
    """
    total = len(ordered_ids)
    n = max(1, int(start_n))
    path = []
    while True:
        window = ordered_ids[:n]
        examined = len(window)
        unread = sum(1 for vid in window if vid not in union)
        exhausted = total <= n
        saturated = unread == examined and examined > 0 and not exhausted
        path.append({
            "n": n,
            "examined": examined,
            "unread": unread,
            "saturated": saturated,
            "exhausted": exhausted,
        })
        if exhausted or not saturated:
            return {
                "settled_n": n,
                "examined": examined,
                "unread": unread,
                "processed": examined - unread,
                "exhausted": exhausted,
                "saturated": saturated,
                "grew": len(path) > 1,
                "growth_path": path,
            }
        n *= 2


def describe_growth(head, start_n):
    """One-line growth path, e.g. '25 saturated (25/25) -> 50 settled (49/50)'."""
    parts = []
    for step in head["growth_path"]:
        if step["saturated"]:
            label = "saturated"
        elif step["exhausted"]:
            label = "exhausted"
        else:
            label = "settled"
        parts.append(f"{step['n']} {label} ({step['unread']}/{step['examined']})")
    if len(parts) == 1:
        return f"{parts[0]} -- settled at the starting window N={start_n}, no growth needed"
    return " -> ".join(parts)


# --------------------------------------------------------------------------
# instrument 2 -- the contiguous frontier
# --------------------------------------------------------------------------

def unread_entries(ordered_ids, titles, union, examined):
    """Every unread entry inside the settled band, named: index + id + title.

    THE HEAD IS A LIST OF VIDEOS, NOT A COUNT. `fetch_playlist_entries` already
    returns {id, title, url}, so titles come free from the enumeration that has
    already happened -- dropping them is a defect, not a saving. A census that says
    "49 unread" without saying WHICH 49 cannot be acted on, and the caller then
    burns a second pass learning what this run already knew.

    `index` is the 0-based position in the playlist, the SAME convention as the
    contiguous index, so the two instruments can be read against each other without
    an off-by-one.

    Titles are a LABEL, never an identity: the membership test below is `vid not in
    union` -- id only. Creators run title tests and one upload answers to three
    names within hours, so nothing here matches, dedups or diffs on a title.

    THIS IS THE ONE PLACE A MISSING TITLE IS HANDLED. Every title goes through
    display_title(), so an absent or blank one leaves here as `(title unavailable)`
    and never as an empty string or an echoed id. Count it via the playlist's
    `fallbacks` field rather than re-testing for blanks downstream.
    """
    out = []
    for i in range(min(examined, len(ordered_ids))):
        vid = ordered_ids[i]
        if vid in union:
            continue
        out.append({
            "index": i,
            "id": vid,
            "title": display_title(titles[i] if i < len(titles) else None),
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return out


def measure_contiguous(ordered_ids, union):
    """Leading unread run == 0-based index of the first already-processed entry.

    first_processed_index_0based is None when the whole list is unread (there is no
    first processed entry to index).
    """
    frontier = 0
    for vid in ordered_ids:
        if vid in union:
            break
        frontier += 1
    return {
        "contiguous_frontier": frontier,
        "first_processed_index_0based": frontier if frontier < len(ordered_ids) else None,
        "caveat": CONTIGUOUS_CAVEAT,
    }


# --------------------------------------------------------------------------
# the walk -- one flat-playlist enumeration per list, cached
# --------------------------------------------------------------------------

def load_cache():
    if not CACHE_FILE.exists():
        return None
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log(f"  [cache] unreadable ({e}) -- treating as absent")
        return None


def save_cache(cache):
    """Write the walk cache.

    This is the ONLY file this tool writes, and it is not seen-state: nothing
    downstream reads it as a processed marker.
    """
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def cache_age_hours(fetched_at):
    try:
        then = datetime.fromisoformat(fetched_at)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0


def selected_playlists(name=None):
    """The configured playlists to census, in config order.

    Raises ValueError on an unresolvable --playlist name, never silently censusing
    everything instead.
    """
    playlists = load_playlists()
    if not name:
        return playlists
    wanted = name.strip().casefold()
    match = next(
        (p for p in playlists if (p.get("name") or "").strip().casefold() == wanted), None
    )
    if not match:
        known = ", ".join(repr(p.get("name")) for p in playlists) or "(none configured)"
        raise ValueError(f"No playlist named {name!r} in data/playlists.json. Known: {known}")
    return [match]


def list_id_of(entry):
    return (
        entry.get("id")
        or parse_list_id(entry.get("url") or "")
        or parse_list_id(entry.get("url_or_id") or "")
    )


def walk_playlist(entry, cookies_path):
    """ONE flat-playlist enumeration. Returns (ids, titles, note).

    `note` is non-None when the enumeration could not be trusted -- an empty return
    from fetch_playlist_entries means a rate-limit refusal, a private/unlisted list,
    or a yt-dlp failure, and those must be reported as UNMEASURED rather than as a
    playlist with zero entries.
    """
    list_id = list_id_of(entry)
    entries = fetch_playlist_entries(list_id, None, cookies=cookies_path)
    if not entries:
        reason = "enumeration returned 0 entries"
        try:
            import ratelimit
            st = ratelimit.status()
            if st.get("blocked"):
                reason += (
                    f" -- the rate-limit gate is COOLING for {st['seconds_left']}s "
                    f"({st.get('reason', '')})"
                )
            else:
                reason += " -- private/unlisted list without cookies, or a yt-dlp failure"
        except Exception:
            reason += " -- cause unknown (ratelimit state unreadable)"
        return [], [], reason
    return [e["id"] for e in entries], [e["title"] for e in entries], None


def census(name=None, start_n=DEFAULT_START_N, from_cache=False, cookies=None):
    """The whole census. Returns the result dict; writes nothing but the walk cache."""
    fingerprint_before = manifest_fingerprint()
    union, lanes, lane_warnings = build_union()
    for w in lane_warnings:
        log(f"  [WARN] {w}")

    playlists = selected_playlists(name)
    cache = load_cache() or {"version": CACHE_VERSION, "playlists": {}}
    cached_lists = cache.get("playlists", {})
    cookies_path = None if from_cache else resolve_cookies(cookies)

    results = []
    cache_dirty = False
    for entry in playlists:
        list_id = list_id_of(entry)
        pl_name = entry.get("name") or list_id
        note = None
        cache_info = None

        if from_cache:
            cached = cached_lists.get(list_id)
            if not cached:
                results.append({
                    "name": pl_name, "list_id": list_id, "measured": False,
                    "note": "no cached walk for this list -- re-run without --from-cache",
                })
                continue
            ids = cached.get("ids") or []
            titles = cached.get("titles") or []
            age = cache_age_hours(cached.get("fetched_at"))
            cache_info = {
                "source": "cache",
                "fetched_at": cached.get("fetched_at"),
                "age_hours": round(age, 2) if age is not None else None,
                "stale": bool(age is not None and age > STALE_AFTER_HOURS),
            }
            if cache_info["stale"]:
                log(f"  [stale] cached walk for {pl_name} is {age / 24:.1f} day(s) old -- "
                    "re-run without --from-cache to refresh")
            elif age is None:
                log(f"  [cache] {pl_name}: timestamp unreadable -- age UNKNOWN, "
                    "not trusted as fresh")
        else:
            log(f"  Enumerating {pl_name} ({list_id}) ...")
            ids, titles, note = walk_playlist(entry, cookies_path)
            if not note:
                cached_lists[list_id] = {
                    "name": pl_name,
                    "fetched_at": now_iso(),
                    "total": len(ids),
                    "ids": ids,
                    "titles": titles,
                }
                cache_dirty = True
                cache_info = {
                    "source": "live",
                    "fetched_at": cached_lists[list_id]["fetched_at"],
                    "age_hours": 0.0,
                    "stale": False,
                }

        if note:
            results.append({"name": pl_name, "list_id": list_id, "measured": False, "note": note})
            continue

        head = measure_head(ids, union, start_n)
        contiguous = measure_contiguous(ids, union)
        named = unread_entries(ids, titles, union, head["examined"])
        results.append({
            "name": pl_name,
            "list_id": list_id,
            "measured": True,
            "total_entries": len(ids),
            "sort": entry.get("sort"),
            "cache": cache_info,
            "settled_band": head,
            "growth_summary": describe_growth(head, start_n),
            "contiguous": contiguous,
            "unread_behind_processed": max(
                0, head["unread"] - contiguous["contiguous_frontier"]
            ),
            "unread_entries": named,
            # How many of the named entries lost their title at the source. A
            # degraded record has to be COUNTABLE, not just visible: 0 is a clean
            # list, and a number moving upward is the source degrading, which no
            # amount of reading a list of titles reliably surfaces.
            "fallbacks": sum(1 for e in named if e["title"] == TITLE_UNAVAILABLE),
        })

    if cache_dirty:
        cache["version"] = CACHE_VERSION
        cache["written_at"] = now_iso()
        cache["playlists"] = cached_lists
        save_cache(cache)

    fingerprint_after = manifest_fingerprint()
    return {
        "generated_at": now_iso(),
        "start_n": start_n,
        "from_cache": from_cache,
        "cookies_used": bool(cookies_path),
        "union_total": len(union),
        "union_lanes": lanes,
        "lane_warnings": lane_warnings,
        "read_only": {
            "manifest": str(SEEN_FILE),
            "sha256_before": fingerprint_before,
            "sha256_after": fingerprint_after,
            "held": fingerprint_before == fingerprint_after,
        },
        "cache_file": str(CACHE_FILE),
        "playlists": results,
    }


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def print_report(res):
    header = "\nPLAYLIST CENSUS -- read-only"
    if res["from_cache"]:
        header += "  [from cache, zero network]"
    print(header)
    print(f"generated {res['generated_at']}  |  start N={res['start_n']}")

    lanes = res["union_lanes"]
    print(f"\nalready-processed union: {res['union_total']} id(s) across 3 stores")
    print(f"  manifest {lanes['manifest']}  |  transcripts repo {lanes['transcripts_repo']} "
          f"vault {lanes['transcripts_vault']}  |  sessions repo {lanes['sessions_repo']} "
          f"vault {lanes['sessions_vault']}")
    for w in res["lane_warnings"]:
        print(f"  [WARN] {w}")

    for pl in res["playlists"]:
        print(f"\n{pl['name']}  ({pl['list_id']})")
        if not pl["measured"]:
            print(f"  UNMEASURED -- {pl['note']}")
            continue
        head = pl["settled_band"]
        print(f"  entries enumerated        {pl['total_entries']}")
        if head["exhausted"]:
            print(f"  SETTLED BAND              {head['unread']} unread / "
                  f"{head['examined']} examined -- LIST EXHAUSTED "
                  f"(no entries past N={head['settled_n']})")
        else:
            print(f"  SETTLED BAND              {head['unread']} unread / "
                  f"{head['examined']} examined (N={head['settled_n']}, unread < N "
                  "so the head is not saturated)")
        print(f"  head window               {pl['growth_summary']}")
        cont = pl["contiguous"]
        idx = cont["first_processed_index_0based"]
        shown = idx if idx is not None else "none -- whole list unread"
        print(f"  CONTIGUOUS FRONTIER       {cont['contiguous_frontier']} "
              f"(0-based index of the first already-processed entry: {shown})")
        print(f"    ^ {cont['caveat']}")
        if pl["unread_behind_processed"]:
            print(f"    ^ {pl['unread_behind_processed']} unread entr(ies) in the settled "
                  "band sit BEHIND already-processed ones -- invisible to the contiguous walk")
        if pl.get("cache") and pl["cache"]["source"] == "cache":
            age = pl["cache"]["age_hours"]
            flag = " [STALE]" if pl["cache"]["stale"] else ""
            print(f"  walk cache                {age if age is not None else 'age UNKNOWN'} h "
                  f"old{flag} (fetched {pl['cache']['fetched_at']})")
        entries = pl["unread_entries"]
        if entries:
            print(f"  UNREAD HEAD               {len(entries)} entr(ies), named below "
                  "(index = 0-based position in the list, same convention as the "
                  "contiguous index)")
            print("    id is the identity; the title is only a label (creators retitle)")
            if pl.get("fallbacks"):
                print(f"    {pl['fallbacks']} of them read {TITLE_UNAVAILABLE} -- the source "
                      "returned no title (private, deleted or region-blocked); the id and "
                      "url are still good")
            for e in entries:
                print(f"    [{e['index']:>4}]  {e['id']}  {e['title']}")
        else:
            print("  UNREAD HEAD               none -- every entry in the settled band is "
                  "already processed")

    ro = res["read_only"]
    verdict = "UNCHANGED" if ro["held"] else "*** CHANGED -- DEFECT ***"
    print(f"\n[read-only] {SEEN_FILE.name} sha256 {verdict}")
    print(f"  before {ro['sha256_before']}")
    print(f"  after  {ro['sha256_after']}")
    print(f"[cache] walk cached to {res['cache_file']} -- "
          "re-analyse with --from-cache (no network)")


def main():
    force_utf8_console()
    ap = argparse.ArgumentParser(
        description="Read-only census of the configured playlists: a self-growing head "
                    "window plus the contiguous frontier. Marks nothing seen."
    )
    ap.add_argument("--json", action="store_true",
                    help="Emit the result dict as JSON on stdout")
    ap.add_argument("--from-cache", action="store_true",
                    help="Re-analyse the cached walk (data/_census_walk_cache.json). "
                         "Zero network.")
    ap.add_argument("--start-n", type=int, default=DEFAULT_START_N,
                    help=f"Starting head-window size (default {DEFAULT_START_N}). "
                         "Doubles while saturated.")
    ap.add_argument("--cookies", default=None,
                    help="cookies.txt for PRIVATE/unlisted playlists. Falls back to "
                         "$CINOPSIS_COOKIES then data/cookies.txt (same resolution as "
                         "fetch_playlist).")
    ap.add_argument("--playlist", default=None,
                    help="Census one named playlist from data/playlists.json (default: all)")
    args = ap.parse_args()

    try:
        res = census(name=args.playlist, start_n=args.start_n,
                     from_cache=args.from_cache, cookies=args.cookies)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print_report(res)

    if not res["read_only"]["held"]:
        print("FAILED: the seen manifest changed during a read-only census. "
              "This is a defect.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
