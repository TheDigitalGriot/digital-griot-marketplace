#!/usr/bin/env python3
"""Build a Cinopsis comparison session from a FINISHED analysis JSON — no fetching.

The "inject-analysis" method. When transcripts were fetched and analyzed
elsewhere — device-side while the cloud has no YouTube egress, by subagents, or
by any external pipeline — this takes the finished analysis and writes a real
comparison_data.json through Cinopsis's own save_session/persist, so the viewer
and the canonical store work exactly as if compare_videos.py had produced it.

Input JSON (via --input FILE, or stdin):
{
  "title": "My Comparison",                      # optional; auto-named from channels
  "videos": [
    {"id": "VIDEO_ID", "title": "...", "channel": "...", "url": "...",
     "summary": "1-2 sentence synopsis",
     "digest": {"core_takeaway": "...", "key_points": ["..."], "why_it_matters": "..."}}
  ],
  "analysis": {
    "unified_summary": "...",
    "topics": [ {"name","video_coverage","consensus","entries":[{"video_id","timestamp","quote"}]} ],
    "disagreements": [ {"topic","positions":[{"video_id","position"}]} ],
    "key_moments": [ {"video_id","timestamp","label","description"} ]
  },
  "stats": { ... }                               # optional; auto-computed from array lengths
}

Usage:
  python build_session_from_analysis.py --input analysis.json --thumbnails
  cat analysis.json | python build_session_from_analysis.py
  python build_session_from_analysis.py --input a.json --no-persist   # skip canonical promote

See comparison-schema.md (skills/cinopsis/references) for the full field reference.
"""
import sys, os, json, argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_videos as cv


def build(data, fetch_thumbs=False):
    videos = data.get("videos") or []
    if not videos:
        raise SystemExit("error: input JSON has no non-empty 'videos' array")

    for v in videos:
        if not v.get("id"):
            print(f"  [warn] a video is missing 'id' — the viewer keys on it", flush=True)
        v.setdefault("summary", "")
        v.setdefault("digest", {"core_takeaway": "", "key_points": [], "why_it_matters": ""})
        if v.get("id") and not v.get("url"):
            v["url"] = f"https://youtu.be/{v['id']}"
        if fetch_thumbs and v.get("id") and not v.get("thumbnail_base64"):
            try:
                v["thumbnail_base64"] = cv.fetch_thumbnail_base64(v["id"])
            except Exception as e:  # non-fatal — a missing thumbnail must never abort the build
                print(f"  [warn] thumbnail fetch failed for {v['id']} ({e}); continuing", flush=True)
                v["thumbnail_base64"] = None

    analysis = data.get("analysis") or {}
    analysis.setdefault("unified_summary", "")
    analysis.setdefault("topics", [])
    analysis.setdefault("disagreements", [])
    analysis.setdefault("key_moments", [])

    stats = data.get("stats") or {
        "total_videos": len(videos),
        "common_topics": len(analysis["topics"]),
        "disagreements": len(analysis["disagreements"]),
        "key_moments": len(analysis["key_moments"]),
    }

    title = data.get("title")
    if not title:
        chans = ", ".join(v.get("channel", "?") for v in videos[:3])
        title = f"Comparison: {chans}" + (f" +{len(videos) - 3}" if len(videos) > 3 else "")

    return {
        "session": {
            "id": cv.generate_session_id(),
            "title": title,
            "created_at": datetime.now().isoformat(),
            "video_count": len(videos),
        },
        "videos": videos,
        "analysis": analysis,
        "stats": stats,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Build a Cinopsis session from a finished analysis JSON (no fetching).")
    ap.add_argument("--input", help="Path to the analysis JSON (default: read stdin)")
    ap.add_argument("--thumbnails", action="store_true",
                    help="Fetch each video's thumbnail via yt-dlp (non-fatal per video)")
    ap.add_argument("--no-persist", action="store_true",
                    help="Do not promote the session to the canonical sessions dir")
    args = ap.parse_args()

    raw = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    data = json.loads(raw)

    if args.no_persist:
        os.environ["CINOPSIS_NO_PERSIST"] = "1"

    comparison = build(data, fetch_thumbs=args.thumbnails)
    path = cv.save_session(comparison)

    s = comparison["stats"]
    print(f"OK {path}")
    print(f"videos {comparison['session']['video_count']} · topics {s['common_topics']} · "
          f"disagreements {s['disagreements']} · key_moments {s['key_moments']}")
    print("Launch: python scripts/compare_server.py --session "
          f"\"{comparison['session']['title']}\"  (or the printed dir_name)")


if __name__ == "__main__":
    main()
