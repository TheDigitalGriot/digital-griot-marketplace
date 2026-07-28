#!/usr/bin/env python3
"""Fetch latest video listings from subscribed YouTube channels."""
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import argparse

from _utils import find_ytdlp, get_env, DATA_DIR
CHANNELS_FILE = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).parent.parent)) / "data" / "channels.json"
OUTPUT_FILE = DATA_DIR / "videos.json"

AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "gpt", "claude", "gemini", "neural", "openai", "anthropic",
    "transformer", "diffusion", "reinforcement", "chatbot", "agent",
    "deepmind", "nvidia", "autonomous", "robot", "cursor", "copilot",
    "sora", "midjourney", "stable diffusion", "vibe coding"
]


def load_channels():
    if not CHANNELS_FILE.exists():
        return []
    with open(CHANNELS_FILE) as f:
        return json.load(f).get("channels", [])


def fetch_channel_videos(channel, days=3):
    """
    Use yt-dlp flat-playlist + approximate_date to fetch recent channel videos.
    Prefers @handle format (which returns upload_date), falls back to channel_id.
    """
    date_after = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    handle = channel.get("handle")
    channel_id = channel.get("id")
    if handle:
        url = f"https://www.youtube.com/{handle}/videos"
    else:
        url = f"https://www.youtube.com/channel/{channel_id}/videos"

    cmd = [
        find_ytdlp(),
        "--flat-playlist",
        "--dump-json",
        "--playlist-end", "10",
        "--extractor-args", "youtubetab:approximate_date",
        url
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=get_env()
        )
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                v = json.loads(line)
            except json.JSONDecodeError:
                continue

            upload_date = v.get("upload_date") or ""
            # Date filter (approximate_date is approximate, allow 1 day tolerance)
            if upload_date and upload_date < date_after:
                continue

            videos.append({
                "id": v.get("id"),
                "title": v.get("title"),
                "url": f"https://www.youtube.com/watch?v={v.get('id')}",
                "channel_id": channel_id,
                "channel_name": channel.get("name"),
                "upload_date": upload_date,
                "duration": v.get("duration_string", ""),
                "view_count": v.get("view_count", 0),
                "description": v.get("description", "")[:300] if v.get("description") else "",
            })
        return videos
    except subprocess.TimeoutExpired:
        print(f"  Timeout: {channel.get('name')}")
        return []
    except Exception as e:
        print(f"  Error fetching {channel.get('name')}: {e}")
        return []


def is_ai_related(video, extra_keyword=None):
    """Check whether a video is AI-related based on title and description."""
    text = (video.get("title", "") + " " + video.get("description", "")).lower()
    if extra_keyword:
        return extra_keyword.lower() in text
    return any(kw in text for kw in AI_KEYWORDS)


def format_date(upload_date):
    if len(upload_date) == 8:
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return upload_date


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3, help="Fetch videos from the last N days")
    parser.add_argument("--keyword", default=None, help="Extra keyword filter")
    parser.add_argument("--all", action="store_true", help="No filtering, return all videos")
    args = parser.parse_args()

    channels = load_channels()
    if not channels:
        print("No channels configured. Edit data/channels.json")
        return

    all_videos = []
    for ch in channels:
        print(f"Fetching: {ch['name']}...", flush=True)
        videos = fetch_channel_videos(ch, args.days)
        all_videos.extend(videos)
        if videos:
            print(f"  -> {len(videos)} video(s)")

    if args.all:
        filtered = all_videos
    else:
        filtered = [v for v in all_videos if is_ai_related(v, args.keyword)]

    # Sort by upload date (newest first), then by view count descending
    filtered.sort(key=lambda v: (v.get("upload_date", ""), v.get("view_count", 0)), reverse=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "videos": filtered,
            "fetched_at": datetime.now().isoformat(),
            "days": args.days,
            "total": len(filtered)
        }, f, indent=2, ensure_ascii=False)

    print(f"\nFound {len(filtered)} AI-related videos (last {args.days} days)")
    for i, v in enumerate(filtered, 1):
        date = format_date(v.get("upload_date", ""))
        vc = f"{v['view_count']:,}" if v.get("view_count") else "?"
        print(f"  {i}. [{date}] {vc} views | {v['title']} ({v['channel_name']}) {v['duration']}")
        print(f"     {v['url']}")


if __name__ == "__main__":
    main()
