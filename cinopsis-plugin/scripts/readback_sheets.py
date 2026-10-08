#!/usr/bin/env python3
"""Contact sheets for a token-bounded frame read-back of a comparison session.

The cc5-batch1 read-back opened one frame PNG per turn, 247 of them in a single context:
595 turns and 105M cache-read tokens. A 3x3 sheet carries nine steps in one image, so a
reader that looks at sheets instead of frames pays roughly a ninth of the image cost, and
a coordinator can hand each fresh-context subagent a bounded chunk of sheets.

    python scripts/readback_sheets.py --session <dir | dir name | comparison_data.json>
        [--per-sheet 9] [--tile-width 480] [--out DIR]

For each video, its workflow_steps are taken in index order and their frame_ref PNGs are
tiled into <out>/<video_id>_sheet_NN.png, each tile downscaled to --tile-width with the
step index and t_start burnt into a corner label. <out>/manifest.json maps every sheet and
tile position back to {video_id, index, t_start, frame_ref, action, ui_kind, ui_target}.
A missing or unreadable frame becomes a labelled blank tile, never a crash.

Exit 0 = sheets written. Exit 2 = the session could not be read.
"""
import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASPECT = 9 / 16          # frames are captured 1280x720; a blank tile keeps the same shape
GAP = 4
BG = (24, 24, 28)
LABEL_BG = (0, 0, 0)
LABEL_FG = (255, 215, 0)
MISSING_FG = (230, 90, 90)


def resolve_session(arg):
    """Accept a session dir, a dir name under data/sessions, or the JSON file itself."""
    p = Path(arg)
    if p.is_file():
        return p
    for cand in (p, DATA / "sessions" / arg):
        if (cand / "comparison_data.json").is_file():
            return cand / "comparison_data.json"
    raise FileNotFoundError(f"no comparison_data.json for {arg!r}")


def _font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _label(img, text, fg):
    draw = ImageDraw.Draw(img)
    font = _font(max(12, img.width // 22))
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
    pad = 4
    draw.rectangle((0, 0, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), fill=LABEL_BG)
    draw.text((pad - x0, pad - y0), text, fill=fg, font=font)


def make_tile(frame_path, label, width):
    """One tile: the frame scaled to `width`, or a labelled blank when the frame is unusable."""
    height = round(width * ASPECT)
    try:
        if frame_path is None:
            raise FileNotFoundError("no frame_ref")
        with Image.open(frame_path) as im:
            im = im.convert("RGB")
            h = max(1, round(im.height * width / im.width))
            tile = im.resize((width, h), Image.LANCZOS)
        missing = False
    except (OSError, ValueError):
        tile = Image.new("RGB", (width, height), BG)
        missing = True
    _label(tile, label + ("  [no frame]" if missing else ""), MISSING_FG if missing else LABEL_FG)
    return tile, missing


def build_sheets(session_json, out_dir, per_sheet=9, tile_width=480):
    """Write every sheet and the manifest; return the manifest dict."""
    data = json.loads(Path(session_json).read_text(encoding="utf-8"))
    steps = data.get("analysis", {}).get("workflow_steps", [])
    cols = math.ceil(math.sqrt(per_sheet))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    by_video = {}
    for s in steps:
        by_video.setdefault(s.get("video_id"), []).append(s)
    manifest = {"session": str(session_json), "per_sheet": per_sheet, "cols": cols,
                "tile_width": tile_width, "videos": {}, "sheets": []}

    for vid, vsteps in by_video.items():
        vsteps.sort(key=lambda s: s.get("index", 0))
        names = []
        for n, start in enumerate(range(0, len(vsteps), per_sheet), 1):
            chunk = vsteps[start:start + per_sheet]
            tiles, rows = [], []
            for pos, s in enumerate(chunk):
                ref = s.get("frame_ref")
                tile, missing = make_tile(DATA / ref if ref else None,
                                          f"#{s.get('index')}  t{s.get('t_start')}", tile_width)
                tiles.append(tile)
                rows.append({"pos": pos, "row": pos // cols, "col": pos % cols,
                             "video_id": vid, "index": s.get("index"), "t_start": s.get("t_start"),
                             "frame_ref": ref, "frame_missing": missing, "action": s.get("action"),
                             "ui_kind": s.get("ui_kind"), "ui_target": s.get("ui_target")})
            tile_h = max(t.height for t in tiles)
            nrows = math.ceil(len(tiles) / cols)
            sheet = Image.new("RGB", (cols * tile_width + (cols - 1) * GAP,
                                      nrows * tile_h + (nrows - 1) * GAP), BG)
            for pos, tile in enumerate(tiles):
                sheet.paste(tile, ((pos % cols) * (tile_width + GAP), (pos // cols) * (tile_h + GAP)))
            name = f"{vid}_sheet_{n:02d}.png"
            sheet.save(out_dir / name, optimize=True)
            names.append(name)
            manifest["sheets"].append({"sheet": name, "video_id": vid, "tiles": rows})
        manifest["videos"][vid] = {"steps": len(vsteps), "sheets": names}

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", required=True)
    ap.add_argument("--per-sheet", type=int, default=9)
    ap.add_argument("--tile-width", type=int, default=480)
    ap.add_argument("--out", help="default: <session dir>/readback_sheets")
    a = ap.parse_args(argv)
    if a.per_sheet < 1 or a.tile_width < 16:
        ap.error("--per-sheet must be >= 1 and --tile-width >= 16")
    try:
        sj = resolve_session(a.session)
        out = Path(a.out) if a.out else sj.parent / "readback_sheets"
        m = build_sheets(sj, out, a.per_sheet, a.tile_width)
    except (OSError, ValueError) as e:
        print(f"readback_sheets: {e}", file=sys.stderr)
        return 2
    missing = sum(t["frame_missing"] for sh in m["sheets"] for t in sh["tiles"])
    for vid, v in m["videos"].items():
        print(f"  {vid}  steps={v['steps']}  sheets={len(v['sheets'])}")
    print(f"sheets={len(m['sheets'])} missing_frames={missing} out={out}")
    print("READBACK_SHEETS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
