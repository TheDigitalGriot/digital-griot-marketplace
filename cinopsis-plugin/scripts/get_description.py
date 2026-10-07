#!/usr/bin/env python3
"""get_description.py - the R4 description writer, on its own.

One yt-dlp --write-info-json call (no media, no captions) through the lifted Watch
download helpers, behind the ratelimit timedtext door, then:

    data/description_<id>.txt   the video description, verbatim
    data/links_<id>.json        github / gitlab / huggingface links found in it

Descriptions are the authoritative source for titles and repo slugs - captions
garble names. The local-pipeline transcript source writes the same two files as
a side effect of its info-json call.

    python scripts/get_description.py --video-id qSuCPooR3E4
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import DATA_DIR  # noqa: E402

DOOR = "timedtext"


def describe(video_id: str) -> dict:
    """Fetch the info JSON once and write the description + links files."""
    from sources.local_pipeline import _watch_auth, fetch_info, write_description
    try:
        import ratelimit
    except ImportError:
        ratelimit = None
    if ratelimit is not None:
        try:
            ratelimit.check_gate("description", door=DOOR)
        except ratelimit.RateLimited as exc:
            return {"status": "rate-limited", "video_id": video_id, "detail": str(exc)}
    run = None
    try:
        info, run = fetch_info(f"https://www.youtube.com/watch?v={video_id}", Path(DATA_DIR) / "media_runs",
                               **_watch_auth())
    except SystemExit as exc:
        if ratelimit is not None:
            ratelimit.record_outcome(False, str(exc), door=DOOR)
        return {"status": "failed", "video_id": video_id, "detail": str(exc)}
    finally:
        if run is not None:
            shutil.rmtree(run, ignore_errors=True)
    if ratelimit is not None:
        ratelimit.record_outcome(True, door=DOOR)
    written = write_description(video_id, info)
    return {"status": "ok", "video_id": video_id, "title": info.get("title"),
            "chapters": len(info.get("chapters") or []), **written}


def main() -> int:
    from media.runtime import configure_stdio
    configure_stdio()
    ap = argparse.ArgumentParser(description="Write description_<id>.txt + links_<id>.json from one info-json call")
    ap.add_argument("--video-id", required=True)
    args = ap.parse_args()
    from capture_frames import extract_video_id
    result = describe(extract_video_id(args.video_id))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
