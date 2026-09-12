#!/usr/bin/env python3
"""Cinopsis invariant gate -- compute the three store invariants over real data.

Exits NONZERO if any invariant is violated, so this can sit on a ceremony gate.
Python 3, standard library only (plus the repo-local _utils for the data dirs).

WHAT IT CHECKS
--------------
  INV1 ingest-iff             an ingested video is backed by all three ingest
                              artifacts: transcript AND description AND the
                              videos manifest.
  INV2 digest-real            a digest covers only real transcripts -- no digest
                              entry without a backing transcript, unless the
                              record DECLARES a non-transcript provenance.
  INV3 comparison-served-iff  a comparison is served only if data_file AND an
                              index.json entry AND a persisted session all exist
                              -- in BOTH directions (no indexed-but-missing, no
                              on-disk-but-unindexed).

WHERE THE ARTIFACTS LIVE (this is why resolution is cross-dir)
--------------------------------------------------------------
There are two data dirs: the working DATA_DIR (<repo>/data) and the canonical
one the viewer reads (_utils.canonical_data_dir()). persist_session() copytree's
ONLY the session dir -- transcript_<id>.*, description_<id>.txt and videos.json
are NEVER promoted alongside it. A canonical session is therefore backed by
caches that live in the working dir, so every artifact lookup here unions ALL
known data dirs. Checking "next to the session" would report a false violation
for every promoted session in the library.

INTERPRETATION NOTES (ambiguities in the stage contract, resolved to the
simplest reading that is true of THIS codebase -- see the progress file)
------------------------------------------------------------------------
* "has transcript" -- the session record's own non-empty inline `transcript`
  counts, because after promotion the session file IS the record of store;
  a transcript_<id>.json/.txt in any data dir also counts.
* "has description" -- there is no `description` key on a session video record
  (compare_videos.fetch_video_metadata does not emit one). The description of a
  video on disk is description_<id>.txt (data/ or data/_drip/desc), and inside a
  session it is the `summary`/`description` field, or failing that a real
  title + url. Any of those satisfies the leg; a record left at
  fetch_video_metadata's error fallback (title "Unknown", no url) does not.
* "has videos.json" -- a session's video manifest is the `videos` array inside
  comparison_data.json; videos.json is the same manifest under its global name
  (digest_all.load_videos reads data["videos"] out of videos.json exactly as
  compare_server reads it out of comparison_data.json). The leg is checked as:
  session.video_count agrees with the manifest, and the video carries a
  non-empty id (compare_server._build_video_lookup drops falsy ids, which makes
  such a video invisible in the very library view it belongs to).
* INV2 provenance exemption -- backfill_catchups.py legitimately digests some
  videos from their DESCRIPTION, tagging them digest_source="description", and
  tags id-less ones id_status="unresolved". Those declare that no transcript
  backs them, so they are not unbacked CLAIMS. INV2 targets the silent case: a
  digest presented as transcript-derived with no transcript anywhere.

Usage:
  python scripts/verify_invariants.py                  # canonical + working dirs
  python scripts/verify_invariants.py --data-dir DIR   # one specific store
  python scripts/verify_invariants.py --verbose        # list every violation
  python scripts/verify_invariants.py --self-test      # prove the gate fires
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _utils import DATA_DIR, canonical_data_dir  # noqa: E402

MAX_SHOWN = 12  # violations printed per invariant unless --verbose


def _p(text):
    """Console-safe string. Session titles are full of em-dashes and a Windows
    cp1252 stdout raises UnicodeEncodeError on them mid-run (backfill_catchups._p)."""
    return str(text).encode("ascii", "replace").decode("ascii")


# ---------------------------------------------------------------------------
# store discovery
# ---------------------------------------------------------------------------
def resolve_data_dirs(explicit=None):
    """Data dirs to check, de-duplicated, canonical first. Non-existent ones drop."""
    cands = [Path(d) for d in explicit] if explicit else [canonical_data_dir(), DATA_DIR]
    seen, out = set(), []
    for cand in cands:
        if not cand.exists():
            continue
        key = os.path.normcase(os.path.abspath(str(cand)))
        if key not in seen:
            seen.add(key)
            out.append(cand)
    return out


def read_json(path):
    """Parsed JSON, or None if absent/unreadable. Never raises."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Artifacts:
    """Ingest artifacts unioned across every data dir (see module docstring)."""

    def __init__(self, data_dirs):
        self.transcripts = set()
        self.descriptions = set()
        self.catalogue = set()
        for base in data_dirs:
            for pattern in ("transcript_*.json", "transcript_*.txt"):
                for path in base.glob(pattern):
                    self.transcripts.add(path.stem[len("transcript_"):])
            for desc_dir in (base, base / "_drip" / "desc"):
                if desc_dir.exists():
                    for path in desc_dir.glob("description_*.txt"):
                        self.descriptions.add(path.name[len("description_"):-len(".txt")])
            catalogue = read_json(base / "videos.json")
            if isinstance(catalogue, dict):
                for video in catalogue.get("videos", []) or []:
                    if isinstance(video, dict) and video.get("id"):
                        self.catalogue.add(video["id"])


class Session:
    """One session dir: its comparison_data.json plus where it was found."""

    def __init__(self, store, dir_name):
        self.store = store
        self.dir_name = dir_name
        self.path = store.sessions_dir / dir_name
        self.data_file = self.path / "comparison_data.json"
        self.data = read_json(self.data_file)

    @property
    def label(self):
        return f"{self.store.name}/{self.dir_name}"

    @property
    def meta(self):
        return (self.data or {}).get("session", {}) or {}

    @property
    def videos(self):
        return (self.data or {}).get("videos", []) or []

    @property
    def analysis(self):
        return (self.data or {}).get("analysis", {}) or {}


class Store:
    """One data dir's sessions/ tree: the index plus the session dirs on disk."""

    def __init__(self, data_dir, canonical=False):
        self.data_dir = Path(data_dir)
        self.canonical = canonical
        self.sessions_dir = self.data_dir / "sessions"
        self.name = self.data_dir.name
        self.index = self._read_index()
        self.sessions = []
        if self.sessions_dir.exists():
            for sub in sorted(p for p in self.sessions_dir.iterdir() if p.is_dir()):
                if (sub / "comparison_data.json").exists():
                    self.sessions.append(Session(self, sub.name))

    def _read_index(self):
        entries = read_json(self.sessions_dir / "index.json")
        return entries if isinstance(entries, list) else []

    @property
    def indexed_dirs(self):
        return {e.get("dir_name") for e in self.index if e.get("dir_name")}


# ---------------------------------------------------------------------------
# per-video artifact resolution
# ---------------------------------------------------------------------------
def has_transcript(video, artifacts):
    """Inline transcript body, or a transcript_<id> cached in any data dir."""
    if video.get("transcript"):
        return True
    vid = video.get("id")
    return bool(vid) and vid in artifacts.transcripts


def has_description(video, artifacts):
    """description_<id>.txt on disk, an inline summary/description, or real metadata."""
    if video.get("description") or video.get("summary"):
        return True
    vid = video.get("id")
    if vid and vid in artifacts.descriptions:
        return True
    title = (video.get("title") or "").strip()
    return bool(title) and title != "Unknown" and bool(video.get("url"))


def has_digest(video):
    """A populated digest block (compare_videos writes it empty; Claude fills it)."""
    digest = video.get("digest")
    if isinstance(digest, dict):
        return any(bool(v) for v in digest.values())
    return bool(digest)


def declares_non_transcript_source(video):
    """The record itself says its digest did not come from a transcript."""
    source = video.get("digest_source")
    if source and source != "transcript":
        return True
    return video.get("id_status") == "unresolved"


# ---------------------------------------------------------------------------
# the three invariants
# ---------------------------------------------------------------------------
def check_ingest_iff(sessions, artifacts):
    """INV1 -- an ingested video has transcript AND description AND manifest entry."""
    violations, checked = [], 0
    for session in sessions:
        videos = session.videos
        declared = session.meta.get("video_count")
        if videos and isinstance(declared, int) and declared != len(videos):
            violations.append(
                f"{_p(session.label)}: manifest disagrees with itself -- "
                f"session.video_count={declared} but {len(videos)} videos listed")
        for video in videos:
            if not isinstance(video, dict) or not has_transcript(video, artifacts):
                continue  # merely listed, not ingested -- INV2 judges its digest
            checked += 1
            missing = []
            if not has_description(video, artifacts):
                missing.append("description")
            if not video.get("id"):
                missing.append("videos-manifest-id")
            if missing:
                violations.append(
                    f"{_p(session.label)}: ingested video "
                    f"{_p(video.get('id') or video.get('title') or '<no id>')} "
                    f"is missing {' + '.join(missing)}")
    return violations, f"{checked} ingested videos across {len(sessions)} sessions"


def check_digest_real(sessions, artifacts):
    """INV2 -- no digest entry (or key_moment) without a backing transcript."""
    violations, checked = [], 0
    for session in sessions:
        by_id = {v.get("id"): v for v in session.videos
                 if isinstance(v, dict) and v.get("id")}
        for video in session.videos:
            if not isinstance(video, dict) or not has_digest(video):
                continue
            checked += 1
            if has_transcript(video, artifacts) or declares_non_transcript_source(video):
                continue
            violations.append(
                f"{_p(session.label)}: digest for "
                f"{_p(video.get('id') or video.get('title') or '<no id>')} "
                f"has no backing transcript and declares no other source")
        for moment in session.analysis.get("key_moments", []) or []:
            if not isinstance(moment, dict):
                continue
            vid = moment.get("video_id")
            if not vid:
                continue
            checked += 1
            if vid not in by_id:
                violations.append(
                    f"{_p(session.label)}: key_moment cites {_p(vid)}, "
                    f"which is not in the session manifest")
            elif not has_transcript(by_id[vid], artifacts):
                violations.append(
                    f"{_p(session.label)}: key_moment cites {_p(vid)}, "
                    f"which has no backing transcript")
    return violations, f"{checked} digest entries across {len(sessions)} sessions"


def check_comparison_served_iff(stores, canonical_dirs):
    """INV3 -- served iff data_file AND index entry AND a persisted session."""
    violations, checked = [], 0
    for store in stores:
        if not store.sessions_dir.exists():
            continue
        on_disk = {s.dir_name for s in store.sessions}
        # forward: every session dir must be reachable AND persisted
        for session in store.sessions:
            checked += 1
            missing = []
            if session.data is None:
                missing.append("readable data_file")
            if session.dir_name not in store.indexed_dirs:
                missing.append("index.json entry")
            if not store.canonical and session.dir_name not in canonical_dirs:
                missing.append("persisted session")
            if missing:
                violations.append(
                    f"{_p(store.name)}/{_p(session.dir_name)}: served comparison is "
                    f"missing {' + '.join(missing)}")
        # reverse: an index entry with no data on disk 404s in the viewer
        for entry in store.index:
            dir_name = entry.get("dir_name") if isinstance(entry, dict) else None
            if not dir_name or dir_name in on_disk:
                continue
            checked += 1
            violations.append(
                f"{_p(store.name)}/{_p(dir_name)}: indexed as served but has no "
                f"data_file on disk (viewer 404)")
    return violations, f"{checked} comparisons across {len(stores)} stores"


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def run(data_dirs, verbose=False, out=None):
    """Compute all three invariants. Returns 0 when every invariant holds."""
    out = out or sys.stdout
    dirs = resolve_data_dirs(data_dirs)
    if not dirs:
        print("verify_invariants: no data dir found -- nothing to check", file=out)
        return 2

    canonical_key = os.path.normcase(os.path.abspath(str(canonical_data_dir())))
    stores = [Store(d, canonical=os.path.normcase(os.path.abspath(str(d))) == canonical_key)
              for d in dirs]
    # With an explicit single --data-dir there is no separate canonical store to
    # promote into; treat that store as its own canonical so INV3 stays meaningful.
    if len(stores) == 1 and not stores[0].canonical:
        stores[0].canonical = True
    canonical_dirs = set()
    for store in stores:
        if store.canonical:
            canonical_dirs |= {s.dir_name for s in store.sessions}

    artifacts = Artifacts(dirs)
    sessions = [s for store in stores for s in store.sessions]

    print("Cinopsis invariant gate", file=out)
    for store in stores:
        tag = " (canonical)" if store.canonical else ""
        print(f"  store: {_p(store.data_dir)}{tag} -- {len(store.sessions)} sessions, "
              f"{len(store.index)} index entries", file=out)
    print(f"  artifacts: {len(artifacts.transcripts)} transcripts, "
          f"{len(artifacts.descriptions)} descriptions, "
          f"{len(artifacts.catalogue)} videos.json entries", file=out)
    print("", file=out)

    results = [
        ("INV1 ingest-iff", check_ingest_iff(sessions, artifacts)),
        ("INV2 digest-real", check_digest_real(sessions, artifacts)),
        ("INV3 comparison-served-iff", check_comparison_served_iff(stores, canonical_dirs)),
    ]

    failed = 0
    for name, (violations, scope) in results:
        if violations:
            failed += 1
            print(f"{name:28s} FAIL  ({len(violations)} violations; {scope})", file=out)
            shown = violations if verbose else violations[:MAX_SHOWN]
            for line in shown:
                print(f"    - {line}", file=out)
            if len(violations) > len(shown):
                print(f"    ... and {len(violations) - len(shown)} more "
                      f"(--verbose to list them all)", file=out)
        else:
            print(f"{name:28s} PASS  ({scope})", file=out)

    print("", file=out)
    if failed:
        print(f"RESULT: FAIL -- {failed} of 3 invariants violated", file=out)
        return 1
    print("RESULT: PASS -- all 3 invariants hold", file=out)
    return 0


# ---------------------------------------------------------------------------
# self-test: prove the gate actually fires (an unfalsifiable gate is paint)
# ---------------------------------------------------------------------------
def _write_synthetic_store(root):
    """A store that violates all three invariants, on purpose."""
    sessions = root / "sessions"
    good = sessions / "2026-01-01_good"
    bad = sessions / "2026-01-02_bad"
    orphan = sessions / "2026-01-03_orphan"
    for d in (good, bad, orphan):
        d.mkdir(parents=True, exist_ok=True)

    def dump(path, payload):
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    dump(good / "comparison_data.json", {
        "session": {"id": "good1", "title": "good", "created_at": "2026-01-01", "video_count": 1},
        "videos": [{"id": "aaaaaaaaaaa", "title": "Real", "url": "https://y/1",
                    "summary": "s", "transcript": [{"text": "hi"}],
                    "digest": {"core_takeaway": "t"}}],
        "analysis": {"key_moments": []},
    })
    # INV1: ingested video with no description and no id, plus a video_count that
    # disagrees with the manifest.  INV2: a digest with no transcript and no
    # declared source, plus a key_moment citing a video that is not in the manifest.
    dump(bad / "comparison_data.json", {
        "session": {"id": "bad1", "title": "bad", "created_at": "2026-01-02", "video_count": 9},
        "videos": [{"id": "", "title": "Unknown", "transcript": [{"text": "x"}]},
                   {"id": "bbbbbbbbbbb", "title": "No transcript", "url": "https://y/2",
                    "summary": "s", "digest": {"core_takeaway": "claimed"}}],
        "analysis": {"key_moments": [{"video_id": "zzzzzzzzzzz", "label": "ghost"}]},
    })
    # INV3: orphan has a data_file but no index entry; the index also lists a dir
    # that does not exist on disk.
    dump(orphan / "comparison_data.json", {
        "session": {"id": "orphan1", "title": "orphan", "created_at": "2026-01-03",
                    "video_count": 0},
        "videos": [], "analysis": {},
    })
    dump(sessions / "index.json", [
        {"id": "good1", "title": "good", "created_at": "2026-01-01",
         "video_count": 1, "dir_name": "2026-01-01_good"},
        {"id": "bad1", "title": "bad", "created_at": "2026-01-02",
         "video_count": 2, "dir_name": "2026-01-02_bad"},
        {"id": "gone1", "title": "gone", "created_at": "2026-01-04",
         "video_count": 1, "dir_name": "2026-01-04_gone"},
    ])
    (root / "transcript_aaaaaaaaaaa.txt").write_text("hi", encoding="utf-8")


def self_test():
    """Build a store that breaks all three invariants; assert the gate exits nonzero."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "store"
        root.mkdir()
        _write_synthetic_store(root)
        print("verify_invariants --self-test: synthetic violating store at", _p(root))
        print("-" * 60)
        code = run([root], verbose=True)
        print("-" * 60)
        if code == 0:
            print("SELF-TEST FAIL: the gate passed a store built to violate all three.")
            return 1
        print(f"SELF-TEST PASS: gate exited {code} on the synthetic violation.")
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Verify the three Cinopsis store invariants; nonzero exit on violation.")
    ap.add_argument("--data-dir", action="append", default=None,
                    help="Data dir to check (repeatable). Default: canonical + working.")
    ap.add_argument("--verbose", action="store_true", help="List every violation.")
    ap.add_argument("--self-test", action="store_true",
                    help="Run the gate against a synthetic violating store and "
                         "confirm it exits nonzero.")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    return run(args.data_dir, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
