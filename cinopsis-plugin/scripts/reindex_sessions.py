#!/usr/bin/env python3
"""Repair sessions/index.json so every session ON DISK is visible in the viewer.

WHY THIS EXISTS
---------------
compare_server's /api/sessions returns sessions/index.json verbatim, and
/api/session/<id> looks the id up in that same index to find its dir_name. A
session directory holding a perfectly good comparison_data.json is therefore
COMPLETELY INVISIBLE if its index entry is missing -- the data is present but
unreachable. Index drift like that happens when a build is interrupted between
writing the session dir and rewriting the index, or when a dir is copied in by
hand.

This script scans the sessions dir, finds every comparison_data.json whose
dir_name has no index entry, and appends a correct one. It reuses
persist_session._entry_for so the entries it writes are byte-identical in shape
to the ones compare_videos.save_session writes (id, title, created_at,
video_count, dir_name), and persist_session._write_index so ordering
(created_at desc) and encoding (UTF-8, no BOM) match too.

Idempotent: a second run finds nothing to do. Never duplicates -- an entry is
added only when neither its dir_name nor its session id is already indexed.
Purely local; touches no network.

Usage:
  python reindex_sessions.py                 # repair the canonical data dir
  python reindex_sessions.py --dry-run       # report only, write nothing
  python reindex_sessions.py --data-dir DIR  # repair some other data dir
  python reindex_sessions.py --all-data-dirs # canonical AND the working DATA_DIR
"""
import argparse
import json
from pathlib import Path

from _utils import DATA_DIR, canonical_data_dir
from persist_session import _entry_for, _read_index, _write_index


def find_orphans(sessions_dir):
    """Session dirs with a comparison_data.json but no index entry.

    Matches on BOTH dir_name and session id: a dir whose id is already indexed
    under a different dir_name is a duplicate, not an orphan, and re-adding it
    would make one session appear twice in the viewer.
    """
    sessions_dir = Path(sessions_dir)
    if not sessions_dir.exists():
        return [], []
    index = _read_index(sessions_dir / "index.json")
    known_dirs = {e.get("dir_name") for e in index}
    known_ids = {e.get("id") for e in index}

    orphans, unreadable = [], []
    for sub in sorted(p for p in sessions_dir.iterdir() if p.is_dir()):
        if not (sub / "comparison_data.json").exists():
            continue
        if sub.name in known_dirs:
            continue
        try:
            entry = _entry_for(sub.name, sessions_dir)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            # A truncated/corrupt comparison_data.json must not abort the repair
            # of every other orphan -- collect it and keep going.
            unreadable.append((sub.name, str(exc)))
            continue
        if entry.get("id") in known_ids:
            continue
        orphans.append(entry)
        known_ids.add(entry.get("id"))
    return orphans, unreadable


def find_stale(sessions_dir):
    """Index entries whose session dir (or comparison_data.json) is gone.

    Reported, never removed -- deleting a user's index entries is not this
    script's call. A stale entry makes /api/session/<id> 404 in the viewer.
    """
    sessions_dir = Path(sessions_dir)
    return [e for e in _read_index(sessions_dir / "index.json")
            if not (sessions_dir / (e.get("dir_name") or "") / "comparison_data.json").exists()]


def reindex(data_dir, dry_run=False):
    """Append missing index entries for one data dir. Returns the orphan entries added."""
    sessions_dir = Path(data_dir) / "sessions"
    print(f"[reindex] {sessions_dir}")
    if not sessions_dir.exists():
        print("  no sessions dir - nothing to do")
        return []

    orphans, unreadable = find_orphans(sessions_dir)
    stale = find_stale(sessions_dir)

    for name, err in unreadable:
        print(f"  [warn] unreadable session '{name}': {err}")
    for entry in stale:
        print(f"  [warn] stale index entry '{entry.get('dir_name')}' - no data on disk (left in place)")

    if not orphans:
        print(f"  index already complete ({len(_read_index(sessions_dir / 'index.json'))} entries)")
        return []

    for entry in orphans:
        print(f"  + {entry['dir_name']}  ({entry['video_count']} videos)  {entry['title'][:60]}")
    if dry_run:
        print(f"  DRY RUN - would add {len(orphans)} entr{'y' if len(orphans) == 1 else 'ies'}")
        return orphans

    index = _read_index(sessions_dir / "index.json") + orphans
    _write_index(sessions_dir / "index.json", index)
    print(f"  wrote index.json - {len(index)} entries ({len(orphans)} added)")
    return orphans


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Repair sessions/index.json so every session on disk is visible.")
    ap.add_argument("--data-dir", default=None,
                    help="Data dir to repair (default: the canonical plugin data dir).")
    ap.add_argument("--all-data-dirs", action="store_true",
                    help="Repair the canonical data dir AND the working DATA_DIR.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change; write nothing.")
    args = ap.parse_args(argv)

    if args.data_dir:
        targets = [Path(args.data_dir)]
    elif args.all_data_dirs:
        targets, seen = [], set()
        for cand in (canonical_data_dir(), DATA_DIR):
            key = str(cand.resolve()) if cand.exists() else str(cand)
            if key not in seen:
                seen.add(key)
                targets.append(cand)
    else:
        targets = [canonical_data_dir()]

    total = 0
    for target in targets:
        total += len(reindex(target, dry_run=args.dry_run))
    print(f"[reindex] done - {total} entr{'y' if total == 1 else 'ies'} "
          f"{'would be ' if args.dry_run else ''}recovered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
