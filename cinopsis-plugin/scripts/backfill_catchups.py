#!/usr/bin/env python3
"""Rebuild the AI-News catch-up digests as real viewer sessions. NO RE-FETCH.

WHY THIS EXISTS
---------------
The 2026-08-16/20/23/25 catch-ups were digested straight to markdown in
.prism/shared/ and never run through build_session_from_analysis.py. They have no
session dir, no comparison_data.json and no index entry, so the companion viewer
has never shown them. This script reconstructs analysis-JSON for each day purely
from artifacts ALREADY ON DISK -- the catch-up markdown plus cached transcript /
description files -- and pipes it through build_session_from_analysis.py.

It performs NO network access of any kind: no YouTube, no yt-dlp, no thumbnail
fetch (--thumbnails is deliberately never passed).

THE FOUR FILES ARE FOUR DIFFERENT FORMATS
-----------------------------------------
  08-16  '- **Title** *(Channel)* - takeaway'   grouped under '## Theme'. NO ids.
  08-20  '- **`ID` - Title** - *N - takeaway'   grouped under '## Theme'. ids ok.
  08-23  '## ID' + Core Takeaway/Key Points/Why It Matters/Harvest.
  08-25  '## ID - Title' + the same fields (12 deep digests), then
         '### Title' + '`ID` - url' + repo bullets (22 description-based).

ON THE 08-16 VIDEO IDS (read this before "fixing" it)
-----------------------------------------------------
08-16's bullets carry no ids, and its 22 videos are absent from every cached
title index (their descriptions were never pulled). Matching digest text against
cached transcript CONTENT was tried and rejected: only 4 of 23 bullets produced a
confident match and single ids won many unrelated bullets at zero margin. Rather
than fabricate id->title links, those videos get a synthetic
'unresolved-<hash>' id and a YouTube SEARCH url. The synthetic id matters because
compare_server._build_video_lookup() skips any video with a falsy id -- an empty
id would make them invisible in the very library view they belong in. They are
tagged id_status='unresolved' so a real id can be filled in later.

Idempotent: a day whose session title is already in the canonical index is
skipped unless --force.

Usage:
  python backfill_catchups.py --dry-run   # write analysis JSON only, build nothing
  python backfill_catchups.py             # build the missing sessions
  python backfill_catchups.py --force     # rebuild even if already present
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

from _utils import DATA_DIR, canonical_data_dir

SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent
SHARED_DIR = REPO_ROOT / ".prism" / "shared"
ARTIFACT_DIR = REPO_ROOT / ".prism" / "local" / "backfill"
VIDEO_ID_RE = r"[A-Za-z0-9_-]{11}"

DAYS = ["2026-08-16", "2026-08-20", "2026-08-23", "2026-08-25"]


def _p(text):
    """Console-safe string. Catch-up titles are full of em-dashes and stars, and a
    Windows cp1252 stdout raises UnicodeEncodeError on them mid-run."""
    return str(text).encode("ascii", "replace").decode("ascii")


# ---------------------------------------------------------------------------
# id -> title index, assembled from cached artifacts only
# ---------------------------------------------------------------------------
def load_title_index():
    """Map video_id -> title from files already on disk.

    Two cached shapes carry titles:
      data/_ai-batch*.txt      '===== <ID> | <TITLE> ====='
      data/description_<ID>.txt  first line '<TITLE> | len=<N>s'
    Neither is fetched here; both are byproducts of earlier runs.
    """
    index = {}
    for path in sorted(DATA_DIR.glob("_ai-batch*.txt")) + sorted(DATA_DIR.glob("_ai-news-bundle.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(rf"^=====\s*({VIDEO_ID_RE})\s*\|\s*(.+?)\s*=====\s*$", text, re.M):
            index.setdefault(m.group(1), m.group(2).strip())

    for base in (DATA_DIR, DATA_DIR / "_drip" / "desc"):
        if not base.exists():
            continue
        for path in sorted(base.glob("description_*.txt")):
            vid = path.name[len("description_"):-len(".txt")]
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    first = f.readline().strip()
            except OSError:
                continue
            if " | len=" in first:
                title = first.split(" | len=")[0].strip()
                if title:
                    index.setdefault(vid, title)
    return index


def cached_transcript_ids():
    """Video ids with a cached transcript, across both data dirs. Provenance only."""
    ids = set()
    for base in (DATA_DIR, canonical_data_dir()):
        if base.exists():
            for path in base.glob("transcript_*.json"):
                ids.add(path.stem[len("transcript_"):])
    return ids


# ---------------------------------------------------------------------------
# shared field parsing ('Core Takeaway:' / 'Key Points:' / ... blocks)
# ---------------------------------------------------------------------------
def parse_digest_fields(block):
    """Pull the labelled digest fields out of one '## <id>' section body."""
    def scalar(label):
        m = re.search(rf"^{label}:\s*(.+?)\s*$", block, re.M)
        return m.group(1).strip() if m else ""

    def bullets(label):
        m = re.search(rf"^{label}:\s*$\n((?:^[-*] .*$\n?)+)", block, re.M)
        if not m:
            # 'Harvest: <single line>' also occurs (08-25)
            inline = scalar(label)
            return [inline] if inline else []
        return [re.sub(r"^[-*]\s+", "", ln).strip()
                for ln in m.group(1).splitlines() if ln.strip()]

    return {
        "core_takeaway": scalar("Core Takeaway"),
        "key_points": bullets("Key Points"),
        "why_it_matters": scalar("Why It Matters"),
        "harvest": bullets("Harvest"),
    }


def make_video(vid, title, channel, summary, digest, harvest=None, extra=None):
    video = {
        "id": vid,
        "title": title or "Untitled",
        "channel": channel or "",
        "url": f"https://youtu.be/{vid}" if vid and len(vid) == 11 else "",
        "summary": summary or "",
        "digest": {
            "core_takeaway": digest.get("core_takeaway", ""),
            "key_points": digest.get("key_points", []),
            "why_it_matters": digest.get("why_it_matters", ""),
        },
    }
    if harvest:
        video["harvest"] = harvest
    if extra:
        video.update(extra)
    return video


def derive_title(core_takeaway, limit=72):
    """Short human label from a digest when the real YouTube title was never captured.

    The 08-23 catch-up recorded only '## <id>' headers, and those ids appear in no
    cached title source, so there is no real title to recover offline. A bare
    11-char id is useless as a library label, so entries fall back to a clipped
    Core Takeaway -- tagged title_status='derived-from-digest' so nothing mistakes
    it for the actual YouTube title.
    """
    text = re.sub(r"\s+", " ", (core_takeaway or "").strip())
    if not text:
        return ""
    if len(text) <= limit:
        return text.rstrip(".")
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "..."


def unresolved_id(title):
    """Stable synthetic id for a video whose real id could not be recovered.

    Filename-safe (no colon -- capture_frame names frame files after the id) and
    obviously not an 11-char YouTube id, so it can never be mistaken for one.
    """
    return "unresolved-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]


def search_url(title):
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(title)


def theme_sections(md):
    """Split '## Theme' sections -> [(name, body)], skipping the doc's H1."""
    parts = re.split(r"^## +(.+?)\s*$", md, flags=re.M)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


# ---------------------------------------------------------------------------
# per-day parsers
# ---------------------------------------------------------------------------
def parse_2026_08_16(md, titles):
    """'- **Title** *(Channel)* - takeaway' bullets under themes. No ids available."""
    videos, topics = [], []
    for name, body in theme_sections(md):
        if name.lower().startswith("tl;dr"):
            continue
        entries = []
        for m in re.finditer(
                r"^-\s+\*\*(?P<title>.+?)\*\*\s*\*\((?P<channel>.+?)\)\*\s*[—-]\s*(?P<tail>.*)$",
                body, re.M):
            title = re.sub(r"[*`]", "", m.group("title")).strip()
            channel = m.group("channel").strip()
            tail = m.group("tail").strip()
            # a few bullets name their id inline (the captions-disabled ones)
            inline = re.search(rf"`({VIDEO_ID_RE})`", tail)
            if inline:
                vid, extra = inline.group(1), {"id_status": "inline"}
            else:
                vid, extra = unresolved_id(title), {"id_status": "unresolved"}
            video = make_video(vid, titles.get(vid, title), channel, tail,
                               {"core_takeaway": tail}, extra=extra)
            if extra["id_status"] == "unresolved":
                video["url"] = search_url(title)
            videos.append(video)
            entries.append({"video_id": vid, "timestamp": "", "quote": tail})
        if entries:
            topics.append({"name": name, "video_coverage": len(entries),
                           "consensus": "", "entries": entries})
    return videos, topics


def parse_2026_08_20(md, titles):
    """'- **`ID` - Title** - *N - takeaway' bullets under themes."""
    videos, topics, seen = [], [], set()
    # TL;DR paragraphs carry a richer blurb keyed by id -- fold them into summary.
    tldr = {}
    for m in re.finditer(rf"^\d+\.\s+\*\*(?P<t>.+?)\*\*\s*\(`(?P<id>{VIDEO_ID_RE})`\):\s*(?P<body>.+?)$",
                         md, re.M):
        tldr[m.group("id")] = m.group("body").strip()

    for name, body in theme_sections(md):
        if name.lower().startswith("tl;dr"):
            continue
        entries = []
        for m in re.finditer(
                rf"^-\s+\*\*`(?P<id>{VIDEO_ID_RE})`\s*·\s*(?P<title>.+?)\*\*\s*[—-]\s*(?P<tail>.*)$",
                body, re.M):
            vid = m.group("id")
            title = re.sub(r"[*`]", "", m.group("title")).strip()
            tail = m.group("tail").strip()
            stars = re.match(r"^⭐(\d)\s*[—-]\s*(.*)$", tail)
            rating, takeaway = (int(stars.group(1)), stars.group(2).strip()) if stars else (None, tail)
            summary = tldr.get(vid) or takeaway
            extra = {"id_status": "ok"}
            if rating:
                extra["signal_rating"] = rating
            if vid not in seen:
                seen.add(vid)
                videos.append(make_video(vid, titles.get(vid, title), "", summary,
                                         {"core_takeaway": takeaway}, extra=extra))
            entries.append({"video_id": vid, "timestamp": "", "quote": takeaway})
        if entries:
            topics.append({"name": name, "video_coverage": len(entries),
                           "consensus": "", "entries": entries})
    return videos, topics


def parse_id_sections(md, titles):
    """'## <ID>' or '## <ID> - Title' sections carrying the labelled digest fields."""
    videos = []
    pattern = re.compile(rf"^## +({VIDEO_ID_RE})(?: *[—-] *(.+?))? *$", re.M)
    matches = list(pattern.finditer(md))
    for i, m in enumerate(matches):
        vid = m.group(1)
        heading_title = (m.group(2) or "").strip()
        body = md[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(md)]
        fields = parse_digest_fields(body)
        extra = {"id_status": "ok"}
        title = heading_title or titles.get(vid) or ""
        if not title:
            title = derive_title(fields["core_takeaway"]) or vid
            extra["title_status"] = "derived-from-digest"
        videos.append(make_video(vid, title, "", fields["core_takeaway"], fields,
                                 harvest=fields["harvest"], extra=extra))
    return videos


def parse_2026_08_23(md, titles):
    videos = parse_id_sections(md, titles)
    return videos, []


def parse_2026_08_25(md, titles):
    """12 deep '## ID - Title' digests + 22 '### Title' / '`ID` - url' quick-hits."""
    videos = parse_id_sections(md, titles)
    seen = {v["id"] for v in videos}
    quick = []
    blocks = re.split(r"^### +(.+?)\s*$", md, flags=re.M)
    for i in range(1, len(blocks) - 1, 2):
        title, body = blocks[i].strip(), blocks[i + 1]
        m = re.search(rf"`({VIDEO_ID_RE})`", body)
        if not m or m.group(1) in seen:
            continue
        vid = m.group(1)
        seen.add(vid)
        repos = [re.sub(r"^[-*]\s+", "", ln).strip()
                 for ln in body.splitlines()
                 if ln.strip().startswith("- ") and "no repos listed" not in ln]
        summary = ("Description-based entry (no transcript digest). "
                   + (f"{len(repos)} project(s) harvested." if repos else "Single-topic video."))
        quick.append(make_video(vid, titles.get(vid, title), "", summary,
                                {"core_takeaway": title, "key_points": repos[:8],
                                 "why_it_matters": ""},
                                harvest=repos, extra={"id_status": "ok",
                                                      "digest_source": "description"}))
    videos += quick
    topics = []
    if videos:
        deep = [v for v in videos if v.get("digest_source") != "description"]
        if deep:
            topics.append({"name": "Deep transcript digests", "video_coverage": len(deep),
                           "consensus": "", "entries": [
                               {"video_id": v["id"], "timestamp": "",
                                "quote": v["digest"]["core_takeaway"]} for v in deep]})
        if quick:
            topics.append({"name": "Roundups & quick-hits (description-based)",
                           "video_coverage": len(quick), "consensus": "", "entries": [
                               {"video_id": v["id"], "timestamp": "",
                                "quote": v["digest"]["core_takeaway"]} for v in quick]})
    return videos, topics


PARSERS = {
    "2026-08-16": parse_2026_08_16,
    "2026-08-20": parse_2026_08_20,
    "2026-08-23": parse_2026_08_23,
    "2026-08-25": parse_2026_08_25,
}


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
def catchup_path(day):
    return SHARED_DIR / f"AI-News-catchup-{day}.md"


def intro_text(md):
    """The prose paragraph under the H1, used as the unified summary."""
    body = re.sub(r"^#\s+.*$", "", md, count=1, flags=re.M).lstrip()
    for para in body.split("\n\n"):
        para = para.strip()
        if para and not para.startswith(("#", "-", "*", "|", "---")):
            return re.sub(r"\s+", " ", para)
    return ""


def build_analysis(day, titles, cached_ids):
    md = catchup_path(day).read_text(encoding="utf-8")
    videos, topics = PARSERS[day](md, titles)
    if not videos:
        raise ValueError(f"no videos parsed out of {catchup_path(day).name}")

    resolved = [v for v in videos if v.get("id_status") != "unresolved"]
    unresolved = len(videos) - len(resolved)
    with_transcript = sum(1 for v in resolved if v["id"] in cached_ids)

    provenance = (f"Backfilled offline from {catchup_path(day).name} on cached data only "
                  f"(no re-fetch). {len(videos)} videos; {len(resolved)} with recovered "
                  f"YouTube ids, {with_transcript} with a cached transcript.")
    if unresolved:
        provenance += (f" {unresolved} entries kept their digest but could not have their "
                       f"video id recovered offline and carry a synthetic 'unresolved-' id.")

    summary = intro_text(md)
    return {
        "title": f"AI News catch-up - {day}",
        "videos": videos,
        "analysis": {
            "unified_summary": (summary + "\n\n" + provenance).strip(),
            "topics": topics,
            "disagreements": [],
            "key_moments": [],
        },
    }


def existing_titles():
    index_file = canonical_data_dir() / "sessions" / "index.json"
    if not index_file.exists():
        return set()
    with open(index_file, encoding="utf-8") as f:
        return {e.get("title") for e in json.load(f)}


def run_builder(analysis_path):
    """Pipe the analysis JSON through build_session_from_analysis.py.

    Deliberately WITHOUT --thumbnails: that flag is the only network path in the
    builder, and this whole script is offline by contract.
    """
    cmd = [sys.executable, str(SCRIPTS_DIR / "build_session_from_analysis.py"),
           "--input", str(analysis_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPTS_DIR),
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return proc


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Rebuild the AI-News catch-up digests as viewer sessions (offline).")
    ap.add_argument("--days", nargs="*", default=DAYS, help=f"Subset of {DAYS}")
    ap.add_argument("--dry-run", action="store_true",
                    help="Write the analysis JSON and report; build no sessions.")
    ap.add_argument("--force", action="store_true",
                    help="Rebuild even if a session with the same title already exists.")
    args = ap.parse_args(argv)

    titles = load_title_index()
    cached_ids = cached_transcript_ids()
    have = existing_titles()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[backfill] title index: {len(titles)} ids | cached transcripts: {len(cached_ids)}")

    built = skipped = failed = 0
    for day in args.days:
        path = catchup_path(day)
        if not path.exists():
            print(f"[backfill] {day}: MISSING {path.name} - skipped")
            failed += 1
            continue
        try:
            analysis = build_analysis(day, titles, cached_ids)
        except (ValueError, OSError) as exc:
            print(f"[backfill] {day}: parse failed - {_p(exc)}")
            failed += 1
            continue

        out = ARTIFACT_DIR / f"analysis-{day}.json"
        out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
        n = len(analysis["videos"])
        unresolved = sum(1 for v in analysis["videos"] if v.get("id_status") == "unresolved")
        print(f"[backfill] {day}: {n} videos ({unresolved} unresolved id) "
              f"{len(analysis['analysis']['topics'])} topics -> {out.name}")

        if analysis["title"] in have and not args.force:
            print(f"           already in the canonical index - skipped (use --force)")
            skipped += 1
            continue
        if args.dry_run:
            print("           DRY RUN - not built")
            continue

        proc = run_builder(out)
        if proc.returncode != 0:
            print(f"           BUILD FAILED rc={proc.returncode}: {_p(proc.stderr.strip()[:400])}")
            failed += 1
            continue
        print("           " + _p(proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "built"))
        built += 1

    print(f"[backfill] done - built={built} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
