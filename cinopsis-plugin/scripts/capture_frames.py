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
    # Anti-hammer gate (shared chokepoint): refuse WITHOUT touching the network
    # while a cooldown is active; else enforce minimum spacing between calls.
    try:
        import ratelimit
    except Exception:
        ratelimit = None
    if ratelimit is not None:
        try:
            ratelimit.check_gate("frames")
        except ratelimit.RateLimited as e:
            print(f"  {e}")
            return None
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=get_env(), stdin=subprocess.DEVNULL)
    if ratelimit is not None:
        if result.returncode != 0:
            ratelimit.record_outcome(False, (result.stderr or "")[:200])
        else:
            ratelimit.record_outcome(True)
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


# Frames are referenced by PATH, never inlined as base64: a 12-video session is
# already 13.2 MB and the viewer parses the whole file client side. capture_frame
# writes "<video_id>_<int(ts)>.png" into DATA_DIR/"frames", so the path a step
# carries is derivable without the payload ever being kept.
FRAMES_SUBDIR = "frames"

# capture_frames_batch holds every base64 payload of one call in memory before it
# returns. A 90-minute tutorial can legitimately carry 150 steps, so the timestamp
# list is fed to it in bounded slices. This is a caller-side choice only - the
# batch function itself is used exactly as written.
BATCH_CHUNK = 20


def frame_ref_for(video_id, timestamp_seconds, output_dir=None):
    """The frame_ref path for one (video, timestamp), relative to the data dir.

    Mirrors the filename capture_frame() writes. Returns a forward-slash path so
    the value is identical on every platform and safe to embed in JSON.
    """
    name = f"{video_id}_{int(timestamp_seconds)}.png"
    if not output_dir:
        return f"{FRAMES_SUBDIR}/{name}"
    target = Path(output_dir) / name
    try:
        return target.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:
        # Outside the data dir - record it as given rather than inventing a
        # relative path that would not resolve for the consumer.
        return target.as_posix()


def collect_capture_timestamps(comparison_data):
    """Map video_id -> the ordered, de-duplicated timestamps to capture.

    The screen is a primary source, not supporting evidence: these videos show the
    presenter operating the UI while they talk, so a frame at t_start is the
    authoritative record of what the control looked like and what was in it -
    often more reliable than narration that says "click this dropdown" without ever
    naming it. So this takes EVERY workflow step's t_start, never a sample, plus
    the key_moments timestamps.
    """
    analysis = comparison_data.get("analysis") or {}
    wanted = {}

    def want(video_id, ts):
        if not video_id or ts is None:
            return
        try:
            ts = int(float(ts))
        except (TypeError, ValueError):
            return
        if ts < 0:
            return
        # capture_frame caches on int(ts), so a repeat costs nothing - de-duplicate
        # anyway to keep the gate spacing sleep off redundant timestamps.
        seen = wanted.setdefault(video_id, [])
        if ts not in seen:
            seen.append(ts)

    for step in analysis.get("workflow_steps") or []:
        if isinstance(step, dict):
            want(step.get("video_id"), step.get("t_start"))
    for moment in analysis.get("key_moments") or []:
        if isinstance(moment, dict):
            want(moment.get("video_id"), moment.get("timestamp"))

    return wanted


def capture_session_frames(comparison_data, output_dir=None, verbose=True):
    """Capture a frame for every workflow step and key moment, in place.

    Drives the existing capture_frames_batch() and writes frame_ref onto each
    workflow step as a path relative to the data dir - never base64. A step whose
    capture genuinely failed gets frame_ref None, which is the only case that is
    allowed to be null.

    key_moments contribute their timestamps to the sweep but are not given a new
    field: frame_ref belongs to workflow_steps, and the moment cards already have
    their own screenshot path in the viewer.

    Mutates comparison_data and returns {captured, failed, videos, timestamps}.
    """
    wanted = collect_capture_timestamps(comparison_data)
    captured_paths = {}
    captured = failed = 0

    for video_id, timestamps in wanted.items():
        for start in range(0, len(timestamps), BATCH_CHUNK):
            chunk = timestamps[start:start + BATCH_CHUNK]
            if verbose:
                print(f"  {video_id}: frames {start + 1}-{start + len(chunk)} of {len(timestamps)}")
            for result in capture_frames_batch(video_id, chunk, output_dir):
                ts = int(result["timestamp"])
                if result["base64"]:
                    # Path only. The payload is a captured/not-captured signal and
                    # is dropped here so it never reaches the session JSON.
                    captured_paths[(video_id, ts)] = frame_ref_for(video_id, ts, output_dir)
                    captured += 1
                else:
                    captured_paths[(video_id, ts)] = None
                    failed += 1

    analysis = comparison_data.get("analysis") or {}
    for step in analysis.get("workflow_steps") or []:
        if not isinstance(step, dict):
            continue
        try:
            ts = int(float(step.get("t_start")))
        except (TypeError, ValueError):
            step["frame_ref"] = None
            continue
        step["frame_ref"] = captured_paths.get((step.get("video_id"), ts))

    return {
        "captured": captured,
        "failed": failed,
        "videos": len(wanted),
        "timestamps": sum(len(v) for v in wanted.values()),
    }


# ---------------------------------------------------------------------------
# --engine local: the per-step engine (Gavin's ruling, cc5-batch1 stage 0).
# The stream engine above resolves a stream URL and seeks it ONCE PER TIMESTAMP, so
# a 120-step video costs 120 yt-dlp URL resolutions against the frames gate. The
# local engine downloads each video ONCE (media.download.download_url, 720p cap,
# behind the same "frames" gate), lets the lifted frames.extract_at_timestamps cut
# exactly one frame at every step t_start and key_moment timestamp, writes
# frames/<video_id>_<int t>.png, sets frame_ref as a relative path, and deletes the
# downloaded video. Same filenames as the stream engine, so either engine's frames
# satisfy the other's cache.
# ---------------------------------------------------------------------------
ENGINES = ("stream", "local")
LOCAL_RESOLUTION = 1280   # frames are read back for UI labels: keep the 720p source legible


def _jpg_to_png(src, dst):
    """The lifted engine writes JPEG cues; the schema's frame_ref convention is .png."""
    try:
        from PIL import Image
        with Image.open(src) as im:
            im.save(dst, "PNG")
        return True
    except ImportError:
        result = subprocess.run([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i",
                                 str(src), str(dst)], capture_output=True, timeout=60,
                                env=get_env(), stdin=subprocess.DEVNULL)
        return result.returncode == 0 and Path(dst).exists()


def _download_video(video_id, runs_dir):
    from media import download
    return download.download_url(f"https://www.youtube.com/watch?v={video_id}", runs_dir)


def _reason(exc):
    """The line that explains a failure. yt-dlp prints WARNINGs first and the ERROR last,
    so the head of the message is the wrong end to keep."""
    lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip()]
    for ln in reversed(lines):
        if "ERROR" in ln or "failed" in ln.lower():
            return ln[:200]
    return (lines[-1] if lines else str(exc))[:200]


def capture_video_local(video_id, timestamps, output_dir=None, fetch=None, resolution=LOCAL_RESOLUTION):
    """Download one video once, cut a PNG at every timestamp, delete the download.

    Returns {ts: frame_ref or None, ...} plus a reason string per failed ts. Timestamps
    whose PNG already exists are served from disk; when ALL of them exist the video is
    never downloaded and the network is not touched. Raises ratelimit.RateLimited when
    the frames gate is cooling, before any network call.
    """
    import shutil
    import tempfile
    from media import frames

    out_dir = Path(output_dir) if output_dir else DATA_DIR / FRAMES_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    refs, reasons = {}, {}
    todo = []
    for ts in timestamps:
        ts = int(ts)
        if (out_dir / f"{video_id}_{ts}.png").exists():
            refs[ts] = frame_ref_for(video_id, ts, output_dir)
        elif ts not in todo:
            todo.append(ts)
    if not todo:
        return refs, reasons

    try:
        import ratelimit
    except ImportError:
        ratelimit = None
    if ratelimit is not None:
        ratelimit.check_gate("frames")       # raises RateLimited: no network touched
    media = None
    cue_dir = Path(tempfile.mkdtemp(prefix=f"cues-{video_id}-", dir=out_dir))
    # A private parent for this one download: the lifted downloader makes its run dir inside
    # it, so a FAILED download (which returns no run_dir) is still cleaned up.
    (DATA_DIR / "media_runs").mkdir(parents=True, exist_ok=True)
    runs_dir = Path(tempfile.mkdtemp(prefix=f"frames-{video_id}-", dir=DATA_DIR / "media_runs"))
    try:
        try:
            media = (fetch or _download_video)(video_id, runs_dir)
        except SystemExit as exc:          # the lifted downloader is a CLI: it reports by SystemExit
            if ratelimit is not None:
                ratelimit.record_outcome(False, _reason(exc))
            for ts in todo:
                refs[ts], reasons[ts] = None, f"download failed: {_reason(exc)}"
            return refs, reasons
        if ratelimit is not None and media.get("downloaded", True):
            ratelimit.record_outcome(True)
        # A cue at or past the end of the video gives ffmpeg 8.x no frame, its mjpeg encoder
        # then fails to open, and the lifted engine raises for the WHOLE batch - so one bad
        # timestamp would sink every frame of the video. Probe the duration (lifted ffprobe,
        # local) and keep only cues inside it; if a batch still fails, retry cue by cue.
        try:
            duration = frames.get_metadata(media["video_path"])["duration_seconds"]
        except SystemExit:
            duration = None
        inside = [t for t in todo if duration is None or t < duration]
        for ts in todo:
            if ts not in inside:
                refs[ts], reasons[ts] = None, f"t={ts}s is past the end of the video ({duration:.0f}s)"
        cues, errors = [], {}
        try:
            cues, _meta = frames.extract_at_timestamps(media["video_path"], cue_dir, inside,
                                                       resolution=resolution) if inside else ([], {})
        except SystemExit:
            for ts in inside:
                single = cue_dir / f"t{ts}"
                try:
                    one, _meta = frames.extract_at_timestamps(media["video_path"], single, [ts],
                                                              resolution=resolution)
                    cues.extend(one)
                except SystemExit as exc:
                    errors[ts] = f"extract failed: {_reason(exc)}"
        got = {}
        for cue in cues:
            ts = int(round(cue["requested_timestamp_seconds"]))
            png = out_dir / f"{video_id}_{ts}.png"
            if _jpg_to_png(cue["path"], png) and png.stat().st_size > 0:
                got[ts] = frame_ref_for(video_id, ts, output_dir)
        for ts in inside:
            refs[ts] = got.get(ts)
            if refs[ts] is None:
                reasons[ts] = errors.get(ts, "ffmpeg emitted no frame at this timestamp")
    finally:
        shutil.rmtree(cue_dir, ignore_errors=True)
        if media and media.get("run_dir") and media.get("downloaded", True):
            shutil.rmtree(media["run_dir"], ignore_errors=True)   # the video is deleted after
        shutil.rmtree(runs_dir, ignore_errors=True)
    return refs, reasons


def capture_session_frames_local(comparison_data, output_dir=None, verbose=True, fetch=None):
    """--engine local twin of capture_session_frames: one download per video, in place.

    Writes frame_ref onto every workflow step (relative path, or None only where capture
    failed, with the reason in the returned summary). If the frames gate trips, stops,
    leaves the remaining steps' frame_ref untouched, and reports stopped_by_gate.
    """
    import ratelimit
    wanted = collect_capture_timestamps(comparison_data)
    refs, failures = {}, {}
    summary = {"captured": 0, "failed": 0, "videos": len(wanted),
               "timestamps": sum(len(v) for v in wanted.values()), "engine": "local",
               "downloads": 0, "stopped_by_gate": False, "gate_reason": "", "failures": failures}
    done_videos = set()
    for video_id, timestamps in wanted.items():
        if verbose:
            print(f"  {video_id}: {len(timestamps)} timestamps (local engine)", flush=True)
        cached = all((Path(output_dir) if output_dir else DATA_DIR / FRAMES_SUBDIR)
                     .joinpath(f"{video_id}_{int(t)}.png").exists() for t in timestamps)
        try:
            vrefs, reasons = capture_video_local(video_id, timestamps, output_dir, fetch=fetch)
        except ratelimit.RateLimited as exc:
            summary["stopped_by_gate"] = True
            summary["gate_reason"] = str(exc)
            if verbose:
                print(f"  {exc}", flush=True)
            break
        if not cached:
            summary["downloads"] += 1
        done_videos.add(video_id)
        for ts, ref in vrefs.items():
            refs[(video_id, ts)] = ref
            if ref:
                summary["captured"] += 1
            else:
                summary["failed"] += 1
                failures[f"{video_id}_{ts}"] = reasons.get(ts, "unknown")

    for step in (comparison_data.get("analysis") or {}).get("workflow_steps") or []:
        if not isinstance(step, dict) or step.get("video_id") not in done_videos:
            continue
        try:
            ts = int(float(step.get("t_start")))
        except (TypeError, ValueError):
            step["frame_ref"] = None
            continue
        step["frame_ref"] = refs.get((step.get("video_id"), ts))
    return summary


def resolve_session_file(session):
    """Resolve --session to a comparison_data.json path.

    Accepts the file itself, the session directory, or a session directory name
    under DATA_DIR/sessions.
    """
    candidate = Path(session)
    if candidate.is_file():
        return candidate
    if candidate.is_dir():
        return candidate / "comparison_data.json"
    return DATA_DIR / "sessions" / session / "comparison_data.json"


def capture_session_file(session, output_dir=None, verbose=True, engine="stream"):
    """Load a session, capture every step frame, write frame_ref back to disk."""
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {ENGINES}")
    data_file = resolve_session_file(session)
    if not data_file.exists():
        raise FileNotFoundError(f"No comparison_data.json at {data_file}")

    with open(data_file, encoding="utf-8") as f:
        comparison_data = json.load(f)

    if engine == "local":
        summary = capture_session_frames_local(comparison_data, output_dir, verbose=verbose)
    else:
        summary = capture_session_frames(comparison_data, output_dir, verbose=verbose)

    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(comparison_data, f, indent=2, ensure_ascii=False)

    summary["session_file"] = str(data_file)
    return summary


# ---------------------------------------------------------------------------
# v3: whole-video frame selection with Watch's frame engine (scripts/media/frames.py,
# lifted from claude-video). capture_frame() above grabs ONE frame at a known
# timestamp from a stream URL; capture_keyframes() downloads the video once (720p
# cap, media.download.download_url) and lets the engine choose the frames:
#   keyframes - I-frames only, near-instant (extract_keyframes)
#   scene     - scene cuts, uniform fallback for static video (extract_scene_or_uniform)
# Frames land in DATA_DIR/frames/<id>_<mode>/; the downloaded video is deleted.
# ---------------------------------------------------------------------------
FRAME_MODES = ("keyframes", "scene")


def capture_keyframes(video_id, mode="keyframes", max_frames=50, resolution=512, output_dir=None,
                      dedup=True):
    """Select frames across a whole video. Returns {frames:[{timestamp_seconds, path, frame_ref}], meta}."""
    import shutil
    from media import download, frames
    if mode not in FRAME_MODES:
        raise ValueError(f"mode must be one of {FRAME_MODES}")
    try:
        import ratelimit
        ratelimit.check_gate("frames")
    except ImportError:
        ratelimit = None
    base = Path(output_dir) if output_dir else DATA_DIR / FRAMES_SUBDIR
    out = base / f"{video_id}_{mode}"
    out.mkdir(parents=True, exist_ok=True)
    runs = DATA_DIR / "media_runs"
    media = None
    try:
        try:
            media = download.download_url(f"https://www.youtube.com/watch?v={video_id}", runs)
        except SystemExit as exc:
            if ratelimit is not None:
                ratelimit.record_outcome(False, str(exc))
            raise RuntimeError(str(exc)) from None
        if ratelimit is not None:
            ratelimit.record_outcome(True)
        try:  # the lifted engine reports ffmpeg/ffprobe failure as SystemExit (it is a CLI)
            if mode == "keyframes":
                selected, meta = frames.extract_keyframes(media["video_path"], out, resolution=resolution,
                                                          max_frames=max_frames, dedup=dedup)
            else:
                duration = frames.get_metadata(media["video_path"])["duration_seconds"]
                fps, target = frames.auto_fps(duration, max_frames=max_frames or 100)
                selected, meta = frames.extract_scene_or_uniform(media["video_path"], out, fps, target,
                                                                 resolution=resolution, max_frames=max_frames,
                                                                 dedup=dedup)
        except SystemExit as exc:
            raise RuntimeError(str(exc)) from None
    finally:
        if media and media.get("run_dir"):
            shutil.rmtree(media["run_dir"], ignore_errors=True)
    for f in selected:
        try:
            f["frame_ref"] = Path(f["path"]).resolve().relative_to(DATA_DIR.resolve()).as_posix()
        except ValueError:
            f["frame_ref"] = None
    return {"video_id": video_id, "mode": mode, "frames": selected, "meta": meta, "dir": str(out)}


def main():
    parser = argparse.ArgumentParser(description="Capture video frames at specific timestamps")
    parser.add_argument("--video-id", help="YouTube video ID or URL")
    parser.add_argument("--timestamps", help="Comma-separated timestamps in seconds (e.g., 60,120,300)")
    parser.add_argument("--session", help="Session dir, dir name, or comparison_data.json: capture a frame "
                                         "for every workflow step t_start and key moment, and write "
                                         "frame_ref back into the session")
    parser.add_argument("--output-dir", help="Directory to save frames")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--select", choices=FRAME_MODES, default=None,
                        help="Let Watch's frame engine pick frames across the whole video "
                             "(keyframes = I-frames, scene = scene cuts) instead of --timestamps")
    parser.add_argument("--max-frames", type=int, default=50, help="Cap for --select (default 50)")
    parser.add_argument("--engine", choices=ENGINES, default="stream",
                        help="--session engine: stream = seek a stream URL per timestamp (original); "
                             "local = download each video once, cut every step frame, delete the video")
    args = parser.parse_args()

    if args.select:
        if not args.video_id:
            parser.error("--select needs --video-id")
        result = capture_keyframes(extract_video_id(args.video_id), args.select, args.max_frames,
                                   output_dir=args.output_dir)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"  {len(result['frames'])} frames ({result['meta'].get('engine')}) -> {result['dir']}")
            for f in result["frames"]:
                print(f"  [{format_timestamp(int(f['timestamp_seconds']))}] {f['path']}")
        return

    if args.session:
        summary = capture_session_file(args.session, args.output_dir, verbose=not args.json,
                                       engine=args.engine)
        if args.json:
            print(json.dumps(summary, indent=2))
            if summary.get("stopped_by_gate"):
                raise SystemExit(3)
        else:
            print(f"  {summary['captured']} captured, {summary['failed']} failed "
                  f"across {summary['videos']} video(s)")
            for key, why in (summary.get("failures") or {}).items():
                print(f"    failed {key}: {why}")
            if summary.get("stopped_by_gate"):
                print(f"  STOPPED BY FRAMES GATE: {summary['gate_reason']}")
                raise SystemExit(3)
        return

    if not (args.video_id and args.timestamps):
        parser.error("either --session, or both --video-id and --timestamps, is required")

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
