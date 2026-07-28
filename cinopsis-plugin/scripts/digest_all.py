#!/usr/bin/env python3
"""Batch-process videos into a Markdown digest with optional transcripts."""
import json
import os
import argparse
from datetime import datetime
from pathlib import Path

from fetch_videos import main as fetch_main, DATA_DIR as FETCH_DATA_DIR, OUTPUT_FILE as VIDEOS_FILE
from get_transcript import get_transcript_ytdlp, format_transcript

DATA_DIR = Path(os.environ.get("CLAUDE_PLUGIN_DATA", Path(__file__).parent.parent / "data"))
OUTPUT_DIR = DATA_DIR / "output"


def load_videos():
    """Load the cached video list from videos.json."""
    videos_file = DATA_DIR / "videos.json"
    if not videos_file.exists():
        return []
    with open(videos_file) as f:
        data = json.load(f)
    return data.get("videos", [])


def format_date(upload_date):
    if len(upload_date) == 8:
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return upload_date


def generate_digest(videos, include_transcript=True, limit=10):
    """Generate a Markdown digest from a list of videos."""
    today = datetime.now().strftime("%Y-%m-%d")
    videos = videos[:limit]

    md = f"# AI Video Digest {today}\n\n"
    md += f"> {len(videos)} AI-related videos\n\n"
    md += "---\n\n"

    for i, video in enumerate(videos, 1):
        title = video.get("title", "Unknown")
        channel = video.get("channel_name", "Unknown")
        date = format_date(video.get("upload_date", ""))
        url = video.get("url", "")
        duration = video.get("duration", "")
        video_id = video.get("id", "")

        md += f"## {i}. {title}\n\n"
        md += f"- **Channel**: {channel}\n"
        md += f"- **Date**: {date}\n"
        md += f"- **Duration**: {duration}\n"
        md += f"- **Link**: {url}\n\n"

        if include_transcript and video_id:
            print(f"  Fetching transcript for: {title}...", flush=True)
            transcript, lang = get_transcript_ytdlp(video_id)
            if transcript:
                formatted = format_transcript(transcript)
                # Save individual transcript
                transcript_file = DATA_DIR / f"transcript_{video_id}.txt"
                transcript_file.write_text(formatted, encoding="utf-8")

                # Include a truncated version in the digest
                truncated = formatted[:2000]
                if len(formatted) > 2000:
                    truncated += "\n... [truncated, see full transcript file]"
                md += "### Transcript\n\n"
                md += f"```\n{truncated}\n```\n\n"
            else:
                md += "*Transcript unavailable*\n\n"

        md += "### Summary (to be filled by Claude)\n\n"
        md += "[Claude: read the transcript above and write a summary here]\n\n"
        md += "---\n\n"

    return md


def main():
    parser = argparse.ArgumentParser(description="Batch-process videos into a Markdown digest")
    parser.add_argument("--days", type=int, default=3, help="Fetch videos from the last N days")
    parser.add_argument("--limit", type=int, default=10, help="Max number of videos to process")
    parser.add_argument("--no-transcript", action="store_true", help="Skip transcript fetching")
    parser.add_argument("--skip-fetch", action="store_true", help="Use existing videos.json instead of re-fetching")
    args = parser.parse_args()

    if not args.skip_fetch:
        import sys
        sys.argv = ["fetch_videos.py", "--days", str(args.days)]
        print(f"Fetching videos from the last {args.days} days...\n", flush=True)
        fetch_main()
        print()

    videos = load_videos()
    if not videos:
        print("No videos found. Check your channel configuration.")
        return

    print(f"Generating digest for {min(len(videos), args.limit)} videos...\n", flush=True)
    digest = generate_digest(videos, include_transcript=not args.no_transcript, limit=args.limit)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    output_file = OUTPUT_DIR / f"ai_digest_{today}.md"
    output_file.write_text(digest, encoding="utf-8")

    print(f"\nDigest saved to: {output_file}")
    print(f"Videos processed: {min(len(videos), args.limit)}")


if __name__ == "__main__":
    main()
