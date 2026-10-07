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
from fetch_playlist import fetch_playlist_new, private_playlist_hint
from get_transcript import fetch_transcript, format_transcript, integrity_gate, describe_failure
from chrome_session import ChromeProfileLockedError
from capture_frames import (extract_video_id, capture_frame as _capture_frame,
                            capture_session_frames, resolve_session_file, BATCH_CHUNK, DATA_DIR)
from compare_videos import parse_urls, process_video, build_comparison_data, save_session
from compare_server import create_app

from mcp.server.fastmcp import FastMCP

# Passive file-bus channel surface (additive). Guarded so a bus problem can NEVER stop the stdio
# server from booting — the stdio tools below stay the load-bearing path.
try:
    import channel_bus
except Exception as _bus_err:  # pragma: no cover - bus is optional, server must still run
    channel_bus = None
    print(f"[cinopsis] channel_bus unavailable, bus surface disabled: {_bus_err}",
          file=sys.stderr, flush=True)

mcp = FastMCP("cinopsis")

TOOL_NAMES = ["fetch_videos", "fetch_playlist", "get_transcript", "compare_videos", "launch_viewer", "capture_frame",
              "harvest_frames", "doctor", "get_description", "watch_video", "watch_frames"]

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
def fetch_playlist(url: str | None = None, name: str | None = None,
                   playlist_end: int | None = None, include_all: bool = False,
                   seed_only: bool = False, cookies: str | None = None) -> str:
    """Surface newly-added videos from a YouTube playlist (id-based seen-diff).

    Diffs the playlist's entries against a local seen manifest and returns only
    the new video ids. First sight of a playlist seeds its baseline from
    already-processed videos (cached transcripts + comparison sessions), so it
    surfaces just the uncatalogued gap rather than every entry.

    Args:
        url: Playlist URL (playlist?list=… or watch?v=…&list=…) or a bare list id.
        name: A named playlist from data/playlists.json (used if url is omitted).
        playlist_end: Optional cap on how many entries to scan.
        include_all: If true, ignore the manifest and return the full list.
        seed_only: If true, seed the manifest from the current playlist and return
            nothing new (onboard a playlist without a retroactive fetch).
        cookies: Optional path to a cookies.txt (Netscape format) so PRIVATE/unlisted
            playlists resolve. Falls back to $CINOPSIS_COOKIES, then data/cookies.txt.
    """
    with _quiet_stdout():
        try:
            result = fetch_playlist_new(
                ref=url, name=name, playlist_end=playlist_end,
                force_all=include_all, seed_only=seed_only, cookies=cookies,
            )
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
    # A private/unlisted playlist yt-dlp cannot see comes back empty — surface the fix.
    hint = (private_playlist_hint(result["list_id"])
            if result["total_entries"] == 0 and not result["cookies_used"] else None)
    if result["seeded_only"]:
        payload = {
            "list_id": result["list_id"],
            "seeded": result["seeded"],
            "new_ids": [],
            "note": "Seeded the manifest from the current playlist; nothing surfaced.",
        }
        if hint:
            payload["hint"] = hint
        return json.dumps(payload, ensure_ascii=False)
    ids = result["new_ids"]
    payload = {
        "list_id": result["list_id"],
        "total_entries": result["total_entries"],
        "first_run": result["first_run"],
        "new_count": len(ids),
        "new_ids": ids,
        "new_videos": [{"id": v["id"], "title": v["title"], "url": v["url"]} for v in result["new"]],
        "next_step": (
            "No new videos." if not ids else
            f"Fetch transcripts: fetch_transcripts.py --ids {' '.join(ids)} --chunk 5 ; "
            f"then compare_videos.py --urls {' '.join(ids)} --from-cache"
        ),
    }
    if hint:
        payload["hint"] = hint
    return json.dumps(payload, ensure_ascii=False)


@mcp.tool()
def get_transcript(video_id: str, sources: str | None = None) -> str:
    """Fetch the transcript for a single YouTube video (URL or 11-char ID).

    Returns timestamped plain text, or an error message if unavailable.

    Goes through the SAME ladder dispatcher every other surface uses: the cache,
    then the selected transcript sources in order. `sources` is a comma list of
    browser-panel, og-http, gemini-url, local-pipeline, claude; empty uses this
    instance's order (settings transcript_sources, CINOPSIS_TRANSCRIPT_SOURCES,
    default browser-panel). Every rung passes the per-door rate-limit gate.
    Run the `doctor` tool to see which sources are ready.
    """
    vid = extract_video_id(video_id)
    if sources:
        try:
            import sources as _src
            _src.parse_order(sources)
        except ValueError as e:
            return str(e)
    try:
        with _quiet_stdout():
            transcript, lang, method = fetch_transcript(vid, sources=sources or None)
            if transcript:
                from _utils import DATA_DIR
                (DATA_DIR / f"transcript_{vid}.txt").write_text(format_transcript(transcript), encoding="utf-8")
    except ChromeProfileLockedError as e:
        # F1: no Chrome debug port and browser-panel was the last selected source.
        return f"F1 - {e}"

    if not transcript:
        if method == "rate-limited":
            # The gate refused every rung — NO network was touched. Do not retry.
            detail = ""
            try:
                import ratelimit
                st = ratelimit.status()
                if st.get("blocked"):
                    detail = (f" Shared cooldown active for ~{st.get('seconds_left', 0) // 60} min"
                              f" (reason: {st.get('reason') or 'cooldown'}).")
                else:
                    cooling = [f"{n} (~{d.get('seconds_left', 0) // 60} min)"
                               for n, d in (st.get("doors") or {}).items() if d.get("blocked")]
                    if cooling:
                        detail = f" Cooling doors: {', '.join(cooling)}."
            except Exception:
                pass
            return (f"Rate-limit gate refused every rung for {vid}; no request was made "
                    f"and no retry was attempted.{detail} "
                    f"Run `python scripts/ratelimit.py` for the per-door breakdown, or "
                    f"`python scripts/ratelimit.py --reset` after moving to a clean network.")
        return describe_failure(method, vid)

    gate = integrity_gate(transcript)
    return (f"Transcript for {vid} ({lang}, {len(transcript)} entries, via {method}):"
            f"\n\n{gate}\n{format_transcript(transcript)}")


@mcp.tool()
def compare_videos(urls: list[str], title: str | None = None, sources: str | None = None) -> str:
    """Build a comparison session from one or more YouTube URLs/IDs.

    Fetches metadata, thumbnail, and transcript for each video and saves a
    session. Returns the session id and the path to comparison_data.json, whose
    analysis section (unified_summary, topics, disagreements, key_moments) Claude
    should then fill in before calling launch_viewer. `sources` selects the
    transcript sources for this call (comma list; empty = this instance's order).
    """
    if sources:
        try:
            import sources as _src
            _src.parse_order(sources)
        except ValueError as e:
            return json.dumps({"error": str(e)})
    with _quiet_stdout():
        ids = parse_urls(urls)
        videos = [process_video(v, sources=sources or None) for v in ids]
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
def doctor(json_output: bool = False, live: bool = False) -> str:
    """Health of every transcript source and the tools behind it (Agent-Reach doctor model).

    Each source's check really executes what it needs (yt-dlp --version, the
    loopback Chrome debug port, key presence - keys are never printed). Offline by
    default. live=True adds at most ONE lightweight request per network source,
    each behind its rate-limit door (a Gemini model GET; one youtube.com/generate_204).
    """
    from doctor import doctor_text
    with _quiet_stdout():
        return doctor_text(as_json=json_output, live=live)


@mcp.tool()
def get_description(video_id: str) -> str:
    """Write data/description_<id>.txt and data/links_<id>.json (github / gitlab / huggingface).

    One yt-dlp info-json call (no media, no captions), behind the timedtext door.
    Descriptions are the authoritative source for titles and repo slugs.
    """
    from get_description import describe
    vid = extract_video_id(video_id)
    with _quiet_stdout():
        result = describe(vid)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def watch_video(source: str, question: str | None = None, engine: str = "auto",
                detail: str | None = None, start: str | None = None, end: str | None = None) -> str:
    """The Watch verb: frames + transcript of a video (local engine) or Gemini's answer about it.

    engine: auto (gemini when a key exists), gemini, or local. detail: transcript,
    efficient, balanced, token-burner. start/end narrow the range (SS, MM:SS, HH:MM:SS).
    Returns Watch's markdown report; on the local engine it lists frame image paths
    to Read. Working files live under the plugin data dir (watch/<timestamp>).
    """
    from watch_video import run_watch
    argv = [source]
    if question:
        argv += ["--question", question]
    if engine:
        argv += ["--engine", engine]
    if detail:
        argv += ["--detail", detail]
    if start:
        argv += ["--start", start]
    if end:
        argv += ["--end", end]
    with _quiet_stdout():
        code, report = run_watch(argv, capture=True)
    return report if code == 0 else f"watch exited {code}\n\n{report}"


@mcp.tool()
def watch_frames(video_id: str, mode: str = "keyframes", max_frames: int = 50) -> str:
    """Let Watch's frame engine pick frames across a whole video (keyframes or scene).

    Downloads the video once (720p cap), extracts, deletes the video, and returns
    the frame paths, timestamps and frame_ref values under the plugin data dir.
    """
    from capture_frames import capture_keyframes
    vid = extract_video_id(video_id)
    try:
        with _quiet_stdout():
            result = capture_keyframes(vid, mode=mode, max_frames=int(max_frames))
    except Exception as e:  # noqa: BLE001 - surfaced to the caller, never swallowed
        return json.dumps({"status": "failed", "video_id": vid, "error": str(e)})
    return json.dumps({"status": "ok", **result}, ensure_ascii=False, default=str)


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


@mcp.tool()
def harvest_frames(session: str) -> str:
    """Paired harvest pass: write a frame_ref onto every workflow step of a session.

    Calls capture_session_frames() per video, in BATCH_CHUNK slices, and checks the
    ratelimit "frames" gate BETWEEN slices. When the gate is cooling it stops,
    leaves the unframed steps' frame_ref null, and reports them as deferred rather
    than burning them as failures. The session file is rewritten after every slice,
    so calling this again RESUMES: only steps with no frame_ref, or whose PNG is
    missing on disk, are re-entered. `session` is a dir, dir name or
    comparison_data.json path.

    This tool defines NO moment or step model of its own. It reads the companion's
    existing schema (skills/cinopsis/references/comparison-schema.md):
    analysis.workflow_steps[].{video_id, t_start, frame_ref} and
    analysis.key_moments[].{video_id, timestamp}, exactly as capture_frames'
    collect_capture_timestamps() does. key_moments contribute timestamps only; they
    gain no field. A step without a usable video_id or t_start cannot be framed and
    is reported as `malformed`, never counted as a capture failure.
    """
    import ratelimit
    data_file = resolve_session_file(session)
    if not data_file.exists():
        return json.dumps({"status": "failed", "note": f"No comparison_data.json at {data_file}"})
    data = json.loads(data_file.read_text(encoding="utf-8"))
    analysis = data.get("analysis") or {}
    steps = [s for s in analysis.get("workflow_steps") or [] if isinstance(s, dict)]

    def _framed(step):
        ref = step.get("frame_ref")
        return bool(ref) and (DATA_DIR / ref).exists()

    def _usable(step):
        # The two fields the schema requires for a frame to be capturable at all.
        if not step.get("video_id"):
            return False
        try:
            return float(step.get("t_start")) >= 0
        except (TypeError, ValueError):
            return False

    malformed = [s for s in steps if not _usable(s)]
    steps = [s for s in steps if _usable(s)]

    pending = {}
    for step in steps:
        if not _framed(step):
            pending.setdefault(step.get("video_id"), []).append(step)
    moments = [m for m in analysis.get("key_moments") or [] if isinstance(m, dict)]
    summary = {"captured": 0, "failed": 0, "deferred": 0, "stopped_by_gate": False, "seconds_left": 0}

    def _persist():
        tmp = data_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(data_file)

    for video_id, vsteps in pending.items():
        for start in range(0, len(vsteps), BATCH_CHUNK):
            gate = ratelimit.status()
            if gate["blocked"]:
                summary["stopped_by_gate"] = True
                summary["seconds_left"] = gate["seconds_left"]
                break
            chunk = vsteps[start:start + BATCH_CHUNK]
            sub = {"analysis": {"workflow_steps": chunk,
                                "key_moments": [m for m in moments if m.get("video_id") == video_id]
                                if start == 0 else []}}
            with _quiet_stdout():
                res = capture_session_frames(sub, verbose=False)
            summary["captured"] += res["captured"]
            gate = ratelimit.status()
            lost = [s for s in chunk if not _framed(s)]
            if gate["blocked"] and lost:
                # The gate tripped inside this slice: those nulls are not real failures.
                summary["deferred"] += len(lost)
                summary["stopped_by_gate"] = True
                summary["seconds_left"] = gate["seconds_left"]
            else:
                summary["failed"] += len(lost)
            _persist()
            if summary["stopped_by_gate"]:
                break
        if summary["stopped_by_gate"]:
            break

    remaining = sum(1 for s in steps if not _framed(s))
    summary.update({"status": "partial" if summary["stopped_by_gate"] else "ok",
                    "remaining": remaining, "total_steps": len(steps),
                    "malformed": len(malformed),
                    "frames_dir": str(DATA_DIR / "frames"),
                    "session_file": str(data_file)})
    # Known companion defect (MAP B1/B2): PNGs land in DATA_DIR/frames, the viewer's
    # server reads canonical_data_dir()/frames, and no route serves frame_ref. Say so
    # rather than let a green "ok" imply the companion can display these frames.
    try:
        from _utils import canonical_data_dir
        if canonical_data_dir().resolve() != DATA_DIR.resolve():
            summary["warning"] = ("frames written under DATA_DIR differ from the canonical data dir "
                                  "the viewer serves; frame_ref will not resolve there yet")
    except Exception:
        pass
    if summary["stopped_by_gate"]:
        summary["note"] = "Frames gate is cooling. Call harvest_frames again after seconds_left; it resumes."
    return json.dumps(summary, ensure_ascii=False)


def _advertise_bus_surfaces() -> None:
    """Publish Cinopsis's verbs (fetch/digest/compare) onto the shared Griot channel bus, so it
    joins the local/cloud ICM channel architecture like brainstorm/gavel. Writes only to the
    filesystem bus dirs (never stdout) and is fully guarded, so it cannot corrupt the MCP JSON-RPC
    stream or stop the server from serving its stdio tools."""
    if channel_bus is None:
        return
    try:
        channel_bus.advertise_surfaces()
    except Exception as e:  # pragma: no cover - advertisement is best-effort
        print(f"[cinopsis] bus surface advertisement skipped: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    if "--list-tools" in sys.argv:
        print("\n".join(TOOL_NAMES))
        raise SystemExit(0)
    if "--list-bus-verbs" in sys.argv:
        print("\n".join(channel_bus.CINOPSIS_VERBS) if channel_bus else "")
        raise SystemExit(0)
    _advertise_bus_surfaces()
    mcp.run()
