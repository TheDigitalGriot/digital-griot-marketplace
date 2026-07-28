#!/usr/bin/env python3
"""Orchestrator: fetch metadata + transcripts for multiple videos, output comparison_data.json."""
import argparse
import json
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from _utils import find_ytdlp, get_env, DATA_DIR, canonical_data_dir
from capture_frames import extract_video_id, capture_frame
from get_transcript import get_transcript_ytdlp, format_transcript
from persist_session import persist_session
SESSIONS_DIR = DATA_DIR / "sessions"
CANONICAL_SESSIONS_DIR = canonical_data_dir() / "sessions"


def parse_urls(urls):
    """Extract video IDs from a list of URLs or bare IDs."""
    return [extract_video_id(u) for u in urls]


def generate_session_id():
    """Generate a unique session ID."""
    return uuid.uuid4().hex[:12]


def build_session_dir_name(title):
    """Build a filesystem-safe session directory name from a title."""
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    return f"{date_prefix}_{slug}"


def fetch_video_metadata(video_id):
    """Fetch full metadata for a single video using yt-dlp."""
    cmd = [find_ytdlp(), "--dump-json", "--no-download", f"https://www.youtube.com/watch?v={video_id}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=get_env(), stdin=subprocess.DEVNULL)
        info = json.loads(result.stdout)
        return {
            "id": video_id,
            "title": info.get("title", "Unknown"),
            "channel": info.get("channel", "Unknown"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "duration": info.get("duration_string", ""),
            "upload_date": info.get("upload_date", ""),
            "view_count": info.get("view_count", 0),
        }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"  Error fetching metadata for {video_id}: {e}")
        return {
            "id": video_id,
            "title": "Unknown",
            "channel": "Unknown",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "duration": "",
            "upload_date": "",
            "view_count": 0,
        }


def fetch_thumbnail_base64(video_id):
    """Download thumbnail and return as base64 string."""
    import base64
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            find_ytdlp(), "--write-thumbnail", "--skip-download",
            "--convert-thumbnails", "png",
            "-o", os.path.join(tmpdir, "thumb"),
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        subprocess.run(cmd, capture_output=True, timeout=30, env=get_env(), stdin=subprocess.DEVNULL)
        for f in Path(tmpdir).glob("thumb*.png"):
            return base64.b64encode(f.read_bytes()).decode("utf-8")
    return None


def process_video(video_id):
    """Fetch metadata, transcript, and thumbnail for a single video."""
    print(f"\nProcessing: {video_id}", flush=True)

    print("  Fetching metadata...", flush=True)
    metadata = fetch_video_metadata(video_id)

    print(f"  Title: {metadata['title']}", flush=True)
    print(f"  Channel: {metadata['channel']}", flush=True)

    print("  Fetching thumbnail...", flush=True)
    metadata["thumbnail_base64"] = fetch_thumbnail_base64(video_id)

    print("  Fetching transcript...", flush=True)
    transcript, lang = get_transcript_ytdlp(video_id)
    metadata["transcript"] = transcript or []
    metadata["transcript_lang"] = lang

    if transcript:
        formatted = format_transcript(transcript)
        transcript_file = DATA_DIR / f"transcript_{video_id}.txt"
        transcript_file.parent.mkdir(parents=True, exist_ok=True)
        transcript_file.write_text(formatted, encoding="utf-8")
        print(f"  Transcript: {len(transcript)} entries ({lang})", flush=True)
    else:
        print("  Transcript: not available", flush=True)

    metadata["digest"] = {
        "core_takeaway": "",
        "key_points": [],
        "why_it_matters": "",
    }

    return metadata


def build_comparison_data(videos, title="Video Comparison"):
    """
    Build the comparison_data.json structure.
    Note: analysis.topics, analysis.disagreements, analysis.key_moments, and
    analysis.unified_summary are PLACEHOLDER fields — Claude fills them in after
    reading the transcripts. This script only populates the video data.
    """
    session_id = generate_session_id()
    return {
        "session": {
            "id": session_id,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "video_count": len(videos),
        },
        "videos": videos,
        "analysis": {
            "unified_summary": "",
            "topics": [],
            "disagreements": [],
            "key_moments": [],
        },
        "stats": {
            "total_videos": len(videos),
            "common_topics": 0,
            "disagreements": 0,
            "key_moments": 0,
        },
    }


def save_session(comparison_data):
    """Save session to the sessions directory and update the index."""
    session = comparison_data["session"]
    dir_name = build_session_dir_name(session["title"])
    session_dir = SESSIONS_DIR / dir_name
    session_dir.mkdir(parents=True, exist_ok=True)

    data_file = session_dir / "comparison_data.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(comparison_data, f, indent=2, ensure_ascii=False)

    # Update index
    index_file = SESSIONS_DIR / "index.json"
    index = []
    if index_file.exists():
        with open(index_file) as f:
            index = json.load(f)

    index.insert(0, {
        "id": session["id"],
        "title": session["title"],
        "created_at": session["created_at"],
        "video_count": session["video_count"],
        "dir_name": dir_name,
    })

    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print(f"\nSession saved to: {data_file}")

    if not os.environ.get("CINOPSIS_NO_PERSIST"):
        try:
            promoted = persist_session(dir_name, src_sessions=SESSIONS_DIR,
                                       dst_sessions=CANONICAL_SESSIONS_DIR)
            if promoted:
                print(f"Persisted to canonical dir: {promoted}")
        except Exception as e:
            print(f"  [warn] could not persist to canonical dir: {e}")

    return data_file


def list_all_videos():
    """Scan all sessions and return a deduplicated list of videos across sessions.

    Prints a formatted table: video_id | title | channel | duration | session_title.
    Returns a list of unique video dicts, each with added 'session_id' and
    'session_title' fields (from the first session that contained each video).
    """
    index_file = SESSIONS_DIR / "index.json"
    if not index_file.exists():
        print("No sessions found.")
        return []

    with open(index_file, encoding="utf-8") as f:
        index = json.load(f)

    seen_ids = {}  # video_id -> video dict (first occurrence wins)
    for entry in index:
        session_id = entry["id"]
        session_title = entry["title"]
        dir_name = entry["dir_name"]
        data_file = SESSIONS_DIR / dir_name / "comparison_data.json"
        if not data_file.exists():
            continue
        with open(data_file, encoding="utf-8") as f:
            comparison_data = json.load(f)
        for video in comparison_data.get("videos", []):
            vid_id = video.get("id")
            if vid_id and vid_id not in seen_ids:
                enriched = dict(video)
                enriched["session_id"] = session_id
                enriched["session_title"] = session_title
                seen_ids[vid_id] = enriched

    unique_videos = list(seen_ids.values())

    if unique_videos:
        col_w = [12, 40, 25, 10, 35]
        header = (
            f"{'video_id':<{col_w[0]}} | "
            f"{'title':<{col_w[1]}} | "
            f"{'channel':<{col_w[2]}} | "
            f"{'duration':<{col_w[3]}} | "
            f"{'session_title':<{col_w[4]}}"
        )
        print(header)
        print("-" * len(header))
        for v in unique_videos:
            print(
                f"{v.get('id', ''):<{col_w[0]}} | "
                f"{v.get('title', '')[:col_w[1]]:<{col_w[1]}} | "
                f"{v.get('channel', '')[:col_w[2]]:<{col_w[2]}} | "
                f"{v.get('duration', ''):<{col_w[3]}} | "
                f"{v.get('session_title', '')[:col_w[4]]:<{col_w[4]}}"
            )
    else:
        print("No videos found across all sessions.")

    return unique_videos


def load_session_videos(session_id, pick_ids=None):
    """Load video metadata from a previously saved session.

    Looks up session_id in index.json to find the directory, then reads
    comparison_data.json. No re-fetching from YouTube — uses cached data only.

    Args:
        session_id: The session ID string to load.
        pick_ids: Optional list of video IDs to filter by. If None, all videos
                  from the session are returned.

    Returns:
        List of video metadata dicts from the session (filtered by pick_ids if given).
    """
    index_file = SESSIONS_DIR / "index.json"
    if not index_file.exists():
        raise FileNotFoundError("No sessions index found.")

    with open(index_file, encoding="utf-8") as f:
        index = json.load(f)

    entry = next((e for e in index if e["id"] == session_id), None)
    if entry is None:
        raise ValueError(f"Session '{session_id}' not found in index.")

    data_file = SESSIONS_DIR / entry["dir_name"] / "comparison_data.json"
    if not data_file.exists():
        raise FileNotFoundError(f"comparison_data.json not found for session '{session_id}'.")

    with open(data_file, encoding="utf-8") as f:
        comparison_data = json.load(f)

    videos = comparison_data.get("videos", [])
    if pick_ids is not None:
        pick_set = set(pick_ids)
        videos = [v for v in videos if v.get("id") in pick_set]

    return videos


def update_session(session_id, comparison_data):
    """Save an updated comparison_data.json for an existing session.

    Looks up the session's dir_name from index.json, writes the updated data,
    and updates the index entry's video_count to match the new video list length.

    Args:
        session_id: The ID of the existing session to update.
        comparison_data: The full comparison data dict to write.

    Returns:
        Path to the written comparison_data.json file.
    """
    index_file = SESSIONS_DIR / "index.json"
    if not index_file.exists():
        raise FileNotFoundError("No sessions index found.")

    with open(index_file, encoding="utf-8") as f:
        index = json.load(f)

    entry = next((e for e in index if e["id"] == session_id), None)
    if entry is None:
        raise ValueError(f"Session '{session_id}' not found in index.")

    data_file = SESSIONS_DIR / entry["dir_name"] / "comparison_data.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(comparison_data, f, indent=2, ensure_ascii=False)

    # Keep index video_count in sync
    new_count = len(comparison_data.get("videos", []))
    entry["video_count"] = new_count
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    return data_file


def add_videos_to_session(session_id, new_videos):
    """Append new video data to an existing session and reset analysis fields.

    Loads the session's comparison_data.json, appends new_videos to the videos
    list, updates video_count in both session and stats, clears the analysis
    section (unified_summary, topics, disagreements, key_moments), then saves.

    Args:
        session_id: The ID of the session to extend.
        new_videos: List of video metadata dicts to append.

    Returns:
        Path to the updated comparison_data.json file.
    """
    index_file = SESSIONS_DIR / "index.json"
    if not index_file.exists():
        raise FileNotFoundError("No sessions index found.")

    with open(index_file, encoding="utf-8") as f:
        index = json.load(f)

    entry = next((e for e in index if e["id"] == session_id), None)
    if entry is None:
        raise ValueError(f"Session '{session_id}' not found in index.")

    data_file = SESSIONS_DIR / entry["dir_name"] / "comparison_data.json"
    if not data_file.exists():
        raise FileNotFoundError(f"comparison_data.json not found for session '{session_id}'.")

    with open(data_file, encoding="utf-8") as f:
        comparison_data = json.load(f)

    existing_ids = {v.get("id") for v in comparison_data["videos"]}
    new_videos = [v for v in new_videos if v.get("id") not in existing_ids]
    if not new_videos:
        return data_file

    comparison_data["videos"].extend(new_videos)
    new_count = len(comparison_data["videos"])

    comparison_data["session"]["video_count"] = new_count
    comparison_data["stats"]["total_videos"] = new_count

    comparison_data["analysis"]["unified_summary"] = ""
    comparison_data["analysis"]["topics"] = []
    comparison_data["analysis"]["disagreements"] = []
    comparison_data["analysis"]["key_moments"] = []

    return update_session(session_id, comparison_data)


def main():
    parser = argparse.ArgumentParser(description="Compare multiple YouTube videos")
    parser.add_argument("--urls", nargs="+", help="YouTube video URLs or IDs")
    parser.add_argument("--title", default=None, help="Session title (auto-generated if omitted)")
    parser.add_argument("--list-videos", action="store_true", help="List all previously analyzed videos")
    parser.add_argument("--from-session", default=None, help="Pull videos from an existing session ID")
    parser.add_argument("--pick", nargs="+", help="Cherry-pick specific video IDs (use with --from-session)")
    parser.add_argument("--add-to", default=None, help="Add videos to an existing session instead of creating new")
    args = parser.parse_args()

    # Mode 1: List videos
    if args.list_videos:
        list_all_videos()
        return

    if args.pick and not args.from_session:
        parser.error("--pick requires --from-session")

    # Gather videos from library (--from-session / --pick)
    videos = []
    if args.from_session:
        session_videos = load_session_videos(args.from_session, args.pick)
        print(f"Loaded {len(session_videos)} video(s) from session {args.from_session}")
        videos.extend(session_videos)

    # Gather videos from new URLs
    if args.urls:
        video_ids = parse_urls(args.urls)
        print(f"Fetching {len(video_ids)} new video(s)...\n", flush=True)
        for vid in video_ids:
            video_data = process_video(vid)
            videos.append(video_data)

    if not videos:
        parser.error("No videos specified. Use --urls, --from-session, or --list-videos.")

    # Mode 2: Add to existing session
    if args.add_to:
        output_path = add_videos_to_session(args.add_to, videos)
        print(f"\nDone! {len(videos)} video(s) added to session.")
        print(f"Output: {output_path}")
        print("\nClaude: read the comparison_data.json file and fill in the analysis section")
        print("(unified_summary, topics, disagreements, key_moments)")
        return

    # Mode 3: Create new session (default)
    title = args.title or f"Comparison: {', '.join(v['channel'] for v in videos[:3])}"
    if len(videos) > 3:
        title += f" +{len(videos) - 3}"

    comparison_data = build_comparison_data(videos, title)
    output_path = save_session(comparison_data)

    print(f"\nDone! {len(videos)} videos processed.")
    print(f"Output: {output_path}")
    print("\nClaude: read the comparison_data.json file and fill in the analysis section")
    print("(unified_summary, topics, disagreements, key_moments)")


if __name__ == "__main__":
    main()
