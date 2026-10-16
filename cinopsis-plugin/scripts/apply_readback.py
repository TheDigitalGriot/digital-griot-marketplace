#!/usr/bin/env python3
"""Apply frame read-back patches to a comparison session.

A step is upgraded to confidence "shown" ONLY when the read-back saw its control on the frame
AND said, in a structured field, that the frame does not contradict it. Every field is re-checked
against comparison-schema.md here, so a reader's patch can never smuggle in an enum value, options
on a non-option control, or a shown step with no frame on disk.

    python scripts/apply_readback.py --session <dir | dir name | comparison_data.json>
        [--readback-dir DIR] [--dry-run] [VIDEO_ID ...]

Patches are readback_<VIDEO_ID>.json, or chunks readback_<VIDEO_ID>_p<N>.json, in --readback-dir
(default: the session dir). With no VIDEO_IDs, every video that has a patch is applied. The patch
format is skills/cinopsis/references/readback-contract.md.

Denial reads the contract's `contradicts` boolean and `contradicts_reason`, never the free-text
note. The batch copies of this script ran a regex over the note and missed every contradiction
worded another way (drift "Read-back regex misses frame contradictions": 1 manual deny in batch 2,
3 in batch 3). A shown step with no `contradicts` field is REFUSED, not trusted: a reader that did
not answer the question has not cleared the frame.

Exit 0 = applied (or dry run). Exit 2 = the session or a patch could not be read.
"""
import argparse
import json
import sys
from pathlib import Path

from readback_sheets import data_root_for, resolve_session

APPS = {"CC5", "iClone8", "Blender", "other"}
KINDS = {"dropdown", "checkbox", "slider", "button", "field", "menu", "tab", "canvas", "list", "radio", "other"}
OPTION_KINDS = {"dropdown", "menu", "list", "radio"}


class PatchError(ValueError):
    pass


def load_patch(readback_dir, vid):
    """One patch for a video, concatenating webinar chunks (_p<N>) when they exist."""
    readback_dir = Path(readback_dir)
    parts = sorted(readback_dir.glob(f"readback_{vid}_p*.json"))
    files = parts or [readback_dir / f"readback_{vid}.json"]
    steps = []
    for f in files:
        if not f.is_file():
            raise PatchError(f"no read-back patch for {vid} in {readback_dir}")
        chunk = json.loads(f.read_text(encoding="utf-8"))
        if chunk.get("video_id") != vid:
            raise PatchError(f"{f.name}: video_id {chunk.get('video_id')!r} != {vid!r}")
        steps.extend(chunk.get("steps") or [])
    return {"video_id": vid, "steps": steps}


def patched_ids(readback_dir):
    ids = set()
    for f in Path(readback_dir).glob("readback_*.json"):
        stem = f.stem[len("readback_"):]
        head, sep, tail = stem.rpartition("_p")
        ids.add(head if sep and tail.isdigit() else stem)
    return sorted(ids)


def contradicted(step, patch):
    """Why the frame refutes the step, or None. Structured fields only - never the note."""
    flag = patch.get("contradicts")
    if not isinstance(flag, bool):
        return None, "no structured contradicts boolean"
    if flag:
        reason = patch.get("contradicts_reason")
        return (reason.strip() if isinstance(reason, str) and reason.strip()
                else "contradicts with no reason given"), None
    params = patch.get("parameters") or {}
    if isinstance(params, dict):
        if any("screen" in str(k).lower() for k in params):
            return "carries an on-screen reading that differs from the step", None
        clash = [k for k in params if k in step["parameters"] and params[k] != step["parameters"][k]]
        if clash:
            return f"frame value differs for {clash}", None
    return None, None


def schema_errors(kind, app, opts, params, path, target):
    bad = []
    if kind not in KINDS:
        bad.append(f"ui_kind {kind!r}")
    if app not in APPS:
        bad.append(f"app {app!r}")
    if not (isinstance(opts, list) and all(isinstance(o, str) for o in opts)):
        bad.append("ui_options")
    elif opts and kind not in OPTION_KINDS:
        bad.append(f"ui_options on {kind}")
    if not (isinstance(params, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in params.items())):
        bad.append("parameters")
    if not (isinstance(path, list) and all(isinstance(x, str) for x in path)):
        bad.append("ui_path")
    if not isinstance(target, str):
        bad.append("ui_target")
    return bad


def apply_video(steps, patch, frame_root):
    """Mutate this video's steps in place; return its report row."""
    vid = patch["video_id"]
    mine = {s["index"]: s for s in steps if s["video_id"] == vid}
    up, seen, refused, denied, before = 0, 0, [], [], []
    for p in patch["steps"]:
        s = mine.get(p.get("index"))
        if s is None or s["t_start"] != p.get("t_start"):
            refused.append(f"#{p.get('index')}: index/t_start mismatch")
            continue
        seen += 1
        reason = p.get("contradicts_reason")
        if p.get("contradicts") is True and isinstance(reason, str) and reason.lower().startswith("before-action"):
            before.append(f"#{s['index']} t{s['t_start']}")
        if p.get("shown") is not True:
            continue
        why, missing = contradicted(s, p)
        if missing:
            refused.append(f"#{s['index']}: {missing}")
            continue
        if why:
            denied.append(f"#{s['index']} t{s['t_start']}: {why}")
            continue
        if not s.get("frame_ref") or not (Path(frame_root) / s["frame_ref"]).is_file():
            refused.append(f"#{s['index']}: shown without a frame on disk")
            continue
        kind = p.get("ui_kind", s["ui_kind"])
        app = p.get("app", s["app"])
        opts = p.get("ui_options", [])
        params = p.get("parameters", {})
        path = p.get("ui_path") or s["ui_path"]
        target = p.get("ui_target") or s["ui_target"]
        bad = schema_errors(kind, app, opts, params, path, target)
        if bad:
            refused.append(f"#{s['index']}: " + ", ".join(bad))
            continue
        merged = dict(s["parameters"])
        merged.update(params)
        s.update(ui_kind=kind, app=app, ui_options=list(opts) if kind in OPTION_KINDS else [],
                 parameters=merged, ui_path=path, ui_target=target, confidence="shown")
        up += 1
    return {"steps": len(mine), "frame_before_action": before, "read_back": seen,
            "upgraded_to_shown": up, "kept_frame_contradicts": denied, "refused": refused}


def apply_readback(session_json, readback_dir=None, ids=None, dry_run=False):
    session_json = Path(session_json)
    readback_dir = Path(readback_dir) if readback_dir else session_json.parent
    data = json.loads(session_json.read_text(encoding="utf-8"))
    steps = (data.get("analysis") or {}).get("workflow_steps") or []
    frame_root = data_root_for(session_json)
    report = {}
    for vid in (ids or patched_ids(readback_dir)):
        report[vid] = apply_video(steps, load_patch(readback_dir, vid), frame_root)
    if not dry_run:
        tmp = session_json.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(session_json)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", required=True)
    ap.add_argument("--readback-dir", help="default: the session dir")
    ap.add_argument("--dry-run", action="store_true", help="report only; do not write the session")
    ap.add_argument("ids", nargs="*", help="video ids (default: every video with a patch)")
    args = ap.parse_args(argv)
    try:
        session_json = resolve_session(args.session)
        report = apply_readback(session_json, args.readback_dir, args.ids, args.dry_run)
    except (FileNotFoundError, PatchError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
