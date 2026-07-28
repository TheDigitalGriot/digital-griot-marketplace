#!/usr/bin/env python3
"""Local-stdio MCP server for cinopsis.

This is the bridge that makes the plugin work on Claude Cowork (which has no
Bash tool / slash commands / hooks). Every tool wraps the SAME Python functions
the Bash scripts use — no forked logic — so Code and Cowork produce identical
results.

IMPORTANT: the wrapped functions print progress to stdout. On a stdio MCP server
stdout is the JSON-RPC channel, so each tool redirects stdout -> stderr while the
underlying function runs. Bootstrap/log noise must never reach stdout.

Run via the self-bootstrapping launcher (see .mcp.json); it ensures the venv has
all dependencies before this module is imported.
"""
import contextlib
import json
import socket
import sys
import threading
from pathlib import Path

# scripts/ is sys.path[0] when run directly, so these bare imports resolve.
from fetch_videos import load_channels, fetch_channel_videos, is_ai_related, OUTPUT_FILE
from get_transcript import get_transcript_ytdlp, format_transcript, integrity_gate
from capture_frames import extract_video_id, capture_frame as _capture_frame
from compare_videos import parse_urls, process_video, build_comparison_data, save_session
from compare_server import create_app

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cinopsis")

TOOL_NAMES = ["fetch_videos", "get_transcript", "compare_videos", "launch_viewer", "capture_frame"]

_viewer = {"port": None}


@contextlib.contextmanager
def _quiet_stdout():
    """Redirect stdout -> stderr so wrapped functions don't corrupt the MCP stream."""
    with contextlib.redirect_stdout(sys.stderr):
        yield


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ensure_viewer(preferred: int = 5123) -> int:
    """Start the Flask viewer in a daemon thread once; return its port."""
    if _viewer["port"]:
        return _viewer["port"]
    port = preferred if _port_free(preferred) else _free_port()
    app = create_app()
    t = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False,
                               use_reloader=False, threaded=True),
        daemon=True,
    )
    t.start()
    _viewer["port"] = port
    return port


@mcp.tool()
def fetch_videos(days: int = 3, keyword: str | None = None, include_all: bool = False) -> str:
    """List recent videos from the configured YouTube channels.

    Args:
        days: Only include videos uploaded in the last N days.
        keyword: Optional keyword filter (overrides the default AI keyword set).
        include_all: If true, do not filter by topic — return everything.
    """
    with _quiet_stdout():
        channels = load_channels()
        if not channels:
            return "No channels configured. Edit data/channels.json (array of {name, id|handle})."
        all_videos = []
        for ch in channels:
            all_videos.extend(fetch_channel_videos(ch, days))
        filtered = all_videos if include_all else [v for v in all_videos if is_ai_related(v, keyword)]
        filtered.sort(key=lambda v: (v.get("upload_date", ""), v.get("view_count", 0)), reverse=True)
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(
            json.dumps({"videos": filtered, "days": days, "total": len(filtered)},
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if not filtered:
        return f"No matching videos found in the last {days} days."
    lines = [f"Found {len(filtered)} video(s) in the last {days} days:"]
    for i, v in enumerate(filtered, 1):
        lines.append(f"{i}. {v.get('title','?')} — {v.get('channel_name','?')} | {v.get('url','')}")
    return "\n".join(lines)


@mcp.tool()
def get_transcript(video_id: str) -> str:
    """Fetch the transcript for a single YouTube video (URL or 11-char ID).

    Returns timestamped plain text, or an error message if unavailable.
    """
    vid = extract_video_id(video_id)
    with _quiet_stdout():
        transcript, lang = get_transcript_ytdlp(vid)
        if transcript:
            from _utils import DATA_DIR
            (DATA_DIR / f"transcript_{vid}.txt").write_text(format_transcript(transcript), encoding="utf-8")
    if not transcript:
        return f"No transcript available for {vid} (video may require login or have no subtitles)."
    gate = integrity_gate(transcript)
    return f"Transcript for {vid} ({lang}, {len(transcript)} entries):\n\n{gate}\n{format_transcript(transcript)}"


@mcp.tool()
def compare_videos(urls: list[str], title: str | None = None) -> str:
    """Build a comparison session from one or more YouTube URLs/IDs.

    Fetches metadata, thumbnail, and transcript for each video and saves a
    session. Returns the session id and the path to comparison_data.json, whose
    analysis section (unified_summary, topics, disagreements, key_moments) Claude
    should then fill in before calling launch_viewer.
    """
    with _quiet_stdout():
        ids = parse_urls(urls)
        videos = [process_video(v) for v in ids]
        if not title:
            title = f"Comparison: {', '.join(v.get('channel', '?') for v in videos[:3])}"
            if len(videos) > 3:
                title += f" +{len(videos) - 3}"
        data = build_comparison_data(videos, title)
        path = save_session(data)
    return json.dumps({
        "session_id": data["session"]["id"],
        "title": title,
        "video_count": len(videos),
        "comparison_data_path": str(path),
        "next_step": "Read comparison_data.json, fill analysis.{unified_summary,topics,disagreements,key_moments} and per-video digest, then call launch_viewer.",
    }, ensure_ascii=False)


@mcp.tool()
def launch_viewer(session_id: str | None = None, port: int = 5123) -> str:
    """Start the interactive dashboard locally and return a URL to open in a browser.

    Args:
        session_id: Optional session to open directly.
        port: Preferred port (a free one is chosen if it's taken).
    """
    with _quiet_stdout():
        actual = _ensure_viewer(port)
    url = f"http://localhost:{actual}"
    if session_id:
        url += f"?session={session_id}"
    return json.dumps({
        "url": url,
        "note": "Open this link in your browser to view the dashboard.",
    }, ensure_ascii=False)


@mcp.tool()
def capture_frame(video_id: str, timestamp_seconds: int) -> str:
    """Capture a still frame from a video at a timestamp (seconds).

    The frame is saved under the plugin data dir and is served by the dashboard.
    Falls back gracefully (the viewer shows a YouTube thumbnail) on failure.
    """
    vid = extract_video_id(video_id)
    with _quiet_stdout():
        b64 = _capture_frame(vid, int(timestamp_seconds))
    if b64:
        return json.dumps({"status": "ok", "video_id": vid, "timestamp": int(timestamp_seconds)})
    return json.dumps({"status": "failed", "video_id": vid, "timestamp": int(timestamp_seconds),
                       "note": "Frame capture failed; the dashboard will fall back to the YouTube thumbnail."})


if __name__ == "__main__":
    if "--list-tools" in sys.argv:
        print("\n".join(TOOL_NAMES))
        raise SystemExit(0)
    mcp.run()
