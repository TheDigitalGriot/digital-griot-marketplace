#!/usr/bin/env python3
"""Extract video frames at specific timestamps using yt-dlp + ffmpeg."""
import argparse
import base64
import json
import os
import re
import subprocess
from pathlib import Path

from _utils import find_ytdlp, find_ffmpeg, get_env, DATA_DIR


def extract_video_id(url_or_id):
    """Extract YouTube video ID from a URL or return the ID if already bare."""
    patterns = [
        r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return url_or_id


def format_timestamp(seconds):
    """Convert seconds to HH:MM:SS format for ffmpeg."""
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def get_stream_url(video_id):
    """Get the direct stream URL for a YouTube video using yt-dlp."""
    cmd = [
        find_ytdlp(),
        "--get-url",
        "--format", "best[height<=720]",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=get_env(), stdin=subprocess.DEVNULL)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    urls = result.stdout.strip().split("\n")
    return urls[0]


def build_ffmpeg_cmd(stream_url, timestamp_seconds, output_path):
    """Build the ffmpeg command to extract a single frame."""
    ts = format_timestamp(timestamp_seconds)
    return [
        find_ffmpeg(),
        "-ss", ts,
        "-i", stream_url,
        "-frames:v", "1",
        "-q:v", "2",
        "-y",
        str(output_path),
    ]


def capture_frame(video_id, timestamp_seconds, output_dir=None):
    """
    Capture a single frame from a YouTube video at the given timestamp.
    Returns the frame as a base64-encoded PNG string, or None on failure.
    """
    output_dir = Path(output_dir) if output_dir else DATA_DIR / "frames"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{video_id}_{int(timestamp_seconds)}.png"

    # If already captured, return cached
    if output_path.exists():
        return base64.b64encode(output_path.read_bytes()).decode("utf-8")

    print(f"  Getting stream URL for {video_id}...", flush=True)
    stream_url = get_stream_url(video_id)
    if not stream_url:
        print(f"  Failed to get stream URL for {video_id}")
        return None

    print(f"  Capturing frame at {format_timestamp(timestamp_seconds)}...", flush=True)
    cmd = build_ffmpeg_cmd(stream_url, timestamp_seconds, output_path)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30, env=get_env(), stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            print(f"  ffmpeg failed (rc={result.returncode})")
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ffmpeg error: {e}")
        return None

    if output_path.exists() and output_path.stat().st_size > 0:
        return base64.b64encode(output_path.read_bytes()).decode("utf-8")
    return None


def capture_frames_batch(video_id, timestamps, output_dir=None):
    """Capture multiple frames for a single video. Returns list of {timestamp, base64}."""
    results = []
    for ts in timestamps:
        b64 = capture_frame(video_id, ts, output_dir)
        results.append({"timestamp": ts, "base64": b64})
    return results


def main():
    parser = argparse.ArgumentParser(description="Capture video frames at specific timestamps")
    parser.add_argument("--video-id", required=True, help="YouTube video ID or URL")
    parser.add_argument("--timestamps", required=True, help="Comma-separated timestamps in seconds (e.g., 60,120,300)")
    parser.add_argument("--output-dir", help="Directory to save frames")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    video_id = extract_video_id(args.video_id)
    timestamps = [int(t.strip()) for t in args.timestamps.split(",")]

    results = capture_frames_batch(video_id, timestamps, args.output_dir)

    if args.json:
        output = []
        for r in results:
            output.append({
                "video_id": video_id,
                "timestamp": r["timestamp"],
                "has_frame": r["base64"] is not None,
            })
        print(json.dumps(output, indent=2))
    else:
        for r in results:
            status = "OK" if r["base64"] else "FAILED"
            print(f"  [{format_timestamp(r['timestamp'])}] {status}")


if __name__ == "__main__":
    main()
