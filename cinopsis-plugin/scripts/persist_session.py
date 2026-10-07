#!/usr/bin/env python3
"""Promote a built session into the canonical (persistent) data dir.

The dashboard reads from canonical_data_dir(); sessions may be *built* elsewhere
(e.g. the Cowork sandbox). This copies a session dir and merges the sessions
index into the canonical location. Idempotent; a no-op when source == dest.
"""
import argparse
import json
import shutil
from pathlib import Path

from _utils import DATA_DIR, canonical_data_dir


def _read_index(path):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def _write_index(path, entries):
    entries = sorted(entries, key=lambda e: e.get("created_at", ""), reverse=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 WITHOUT BOM (Python json.load rejects a leading BOM)
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _entry_for(dir_name, src_sessions):
    """Index entry for dir_name from the source index, else reconstructed from data."""
    for e in _read_index(src_sessions / "index.json"):
        if e.get("dir_name") == dir_name:
            return e
    with open(src_sessions / dir_name / "comparison_data.json", encoding="utf-8") as f:
        s = json.load(f)["session"]
    return {"id": s["id"], "title": s["title"], "created_at": s["created_at"],
            "video_count": s.get("video_count", 0), "dir_name": dir_name}


def _promote_frames(data_file, src_root, dst_root):
    """Copy every relative frame_ref the session cites into the canonical frames dir (harvest B1).

    capture_session_frames writes PNGs under the working DATA_DIR/frames and records
    `frames/<id>_<t>.png`; the viewer serves canonical/frames. Without this, a session
    promoted from a working copy points at files the canonical server never sees.
    Absolute refs and refs that escape frames/ are left alone. Returns the count copied.
    """
    try:
        data = json.loads(Path(data_file).read_text(encoding="utf-8"))
    except Exception:
        return 0
    src_frames = (Path(src_root) / "frames").resolve()
    dst_frames = (Path(dst_root) / "frames").resolve()
    copied = 0
    for step in (data.get("analysis") or {}).get("workflow_steps") or []:
        ref = step.get("frame_ref") if isinstance(step, dict) else None
        if not ref or not str(ref).startswith("frames/"):
            continue
        src = (Path(src_root) / ref).resolve()
        if not src.is_relative_to(src_frames) or not src.is_file() or src_frames == dst_frames:
            continue
        dst = dst_frames / src.relative_to(src_frames)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    return copied


def persist_session(dir_name, src_sessions=None, dst_sessions=None):
    """Copy <dir_name> from src to canonical dst and merge the index.

    Returns the destination session dir Path, or None if src == dst (no-op).
    """
    src = Path(src_sessions) if src_sessions else DATA_DIR / "sessions"
    dst = Path(dst_sessions) if dst_sessions else canonical_data_dir() / "sessions"
    if src.resolve() == dst.resolve():
        return None

    src_dir = src / dir_name
    if not (src_dir / "comparison_data.json").exists():
        raise FileNotFoundError(f"No session at {src_dir}")

    dst_dir = dst / dir_name
    dst.mkdir(parents=True, exist_ok=True)
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)
    _promote_frames(dst_dir / "comparison_data.json", src.parent, dst.parent)

    entry = _entry_for(dir_name, src)
    index = [e for e in _read_index(dst / "index.json") if e.get("id") != entry["id"]]
    index.append(entry)
    _write_index(dst / "index.json", index)
    return dst_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description="Promote session(s) to the canonical data dir")
    ap.add_argument("dir_name", nargs="?", help="Session directory name to promote")
    ap.add_argument("--all", action="store_true", help="Promote every session in the source dir")
    args = ap.parse_args(argv)

    src = DATA_DIR / "sessions"
    if args.all:
        names = [p.name for p in src.iterdir() if (p / "comparison_data.json").exists()] if src.exists() else []
    elif args.dir_name:
        names = [args.dir_name]
    else:
        ap.error("provide a dir_name or --all")

    for name in names:
        dst = persist_session(name)
        print(f"persisted {name} -> {dst}" if dst else f"{name}: already canonical (no-op)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
