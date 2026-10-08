#!/usr/bin/env python3
"""Schema gate for a comparison session: check comparison_data.json against the full
contract in skills/cinopsis/references/comparison-schema.md and name EVERY violation.

Promoted from the golden-hour run's parse_gate.py (2026-10-06). That script stopped on
the first missing key with a traceback; this one never raises on bad data. It collects
violations and exits non-zero when there are any, so one broken step cannot hide the rest.

    python scripts/validate_comparison.py --session <dir | dir name | comparison_data.json> [--json]

Exit 0 = schema-exact. Exit 1 = violations, each printed. Exit 2 = the file could not be
read or parsed at all.
"""
import argparse
import json
import sys
from pathlib import Path

# The fifteen workflow_steps fields, in schema order. Exactly these, no more, no fewer.
STEP_KEYS = ("video_id", "index", "t_start", "t_end", "phase", "action", "app", "ui_path",
             "ui_kind", "ui_target", "ui_options", "parameters", "result", "frame_ref", "confidence")
KEY_MOMENT_KEYS = {"video_id", "timestamp", "label", "description"}
CHAPTER_KEYS = {"title", "start_time", "end_time"}
DISAGREEMENT_KEYS = {"topic", "positions"}
POSITION_KEYS = {"video_id", "position"}

CONSENSUS = {"agreement", "divided", "skeptical"}
APPS = {"CC5", "iClone8", "Blender", "other"}
UI_KINDS = {"dropdown", "checkbox", "slider", "button", "field", "menu", "tab", "canvas",
            "list", "radio", "other"}
OPTION_KINDS = {"dropdown", "menu", "list", "radio"}
CONFIDENCE = {"spoken", "shown", "inferred"}
UNRESOLVED_TITLES = {"", "unknown", "untitled"}


def _int(x):
    """A JSON integer. bool is a subclass of int in Python and is NOT an integer here."""
    return isinstance(x, int) and not isinstance(x, bool)


def _str(x, nonempty=True):
    return isinstance(x, str) and (bool(x.strip()) if nonempty else True)


def _frame_ref_ok(ref):
    """Relative path or null. Never absolute, never base64, never escaping the data dir."""
    if ref is None:
        return True
    if not _str(ref):
        return False
    if ref.startswith(("data:", "/", "\\")) or (len(ref) > 1 and ref[1] == ":"):
        return False
    if "base64" in ref[:64] or len(ref) > 512:
        return False
    return ".." not in Path(ref.replace("\\", "/")).parts


def chapter_covering(chapters, t):
    """The chapter title whose [start_time, end_time) span covers t, else None."""
    for c in chapters:
        if isinstance(c, dict) and _int(c.get("start_time")) and _int(c.get("end_time")) \
                and c["start_time"] <= t < c["end_time"]:
            return c.get("title")
    return None


def validate(data, data_dir=None, require_per_video=False):
    """Return the list of violation strings for one parsed comparison_data.json.

    data_dir, when given, also checks that every non-null frame_ref exists on disk under it.
    require_per_video additionally demands at least one workflow step AND one key moment per
    video (a batch criterion, not a schema rule: a no-procedure session legitimately has 0).
    """
    errs = []
    if not isinstance(data, dict):
        return ["top level is not an object"]

    # ---- videos ---------------------------------------------------------------
    videos = data.get("videos")
    if not isinstance(videos, list) or not videos:
        errs.append("videos: missing or empty")
        videos = []
    ids, chapters_by_id = [], {}
    for i, v in enumerate(videos):
        if not isinstance(v, dict):
            errs.append(f"videos[{i}]: not an object")
            continue
        vid = v.get("id")
        tag = vid if _str(vid) else f"videos[{i}]"
        if not _str(vid):
            errs.append(f"{tag}: id missing")
        elif vid in ids:
            errs.append(f"{tag}: duplicate video id")
        else:
            ids.append(vid)
        title = v.get("title")
        if not _str(title) or title.strip().lower() in UNRESOLVED_TITLES or title.strip("? ") == "":
            errs.append(f"{tag}: unresolved title {title!r}")
        if not _str(v.get("summary")):
            errs.append(f"{tag}: summary empty")
        dg = v.get("digest")
        if not isinstance(dg, dict):
            errs.append(f"{tag}: digest missing")
        else:
            if not _str(dg.get("core_takeaway")):
                errs.append(f"{tag}: digest.core_takeaway empty")
            kp = dg.get("key_points")
            if not (isinstance(kp, list) and kp and all(_str(p) for p in kp)):
                errs.append(f"{tag}: digest.key_points must be a non-empty array of strings")
            if not _str(dg.get("why_it_matters")):
                errs.append(f"{tag}: digest.why_it_matters empty")
        chs = v.get("chapters")
        if not isinstance(chs, list):
            errs.append(f"{tag}: chapters missing (use [] when the video has none)")
            chs = []
        prev = -1
        for j, c in enumerate(chs):
            if not isinstance(c, dict) or set(c) != CHAPTER_KEYS:
                errs.append(f"{tag}: chapters[{j}] must have exactly {sorted(CHAPTER_KEYS)}")
                continue
            if not (isinstance(c["title"], str) and _int(c["start_time"]) and _int(c["end_time"])):
                errs.append(f"{tag}: chapters[{j}] title str, start_time/end_time int")
                continue
            if c["start_time"] < prev:
                errs.append(f"{tag}: chapters[{j}] out of ascending start_time order")
            prev = c["start_time"]
        if _str(vid):
            chapters_by_id[vid] = chs
    idset = set(ids)

    # ---- analysis -------------------------------------------------------------
    a = data.get("analysis")
    if not isinstance(a, dict):
        errs.append("analysis: missing")
        a = {}
    if not _str(a.get("unified_summary")):
        errs.append("analysis.unified_summary empty")

    topics = a.get("topics")
    if not isinstance(topics, list):
        errs.append("analysis.topics: not an array")
        topics = []
    for i, t in enumerate(topics):
        if not isinstance(t, dict):
            errs.append(f"topics[{i}]: not an object")
            continue
        name = t.get("name") if _str(t.get("name")) else f"topics[{i}]"
        if not _str(t.get("name")):
            errs.append(f"{name}: name empty")
        if t.get("consensus") not in CONSENSUS:
            errs.append(f"topic {name!r}: consensus {t.get('consensus')!r} not in {sorted(CONSENSUS)}")
        cov = t.get("video_coverage")
        if not isinstance(cov, list) or not all(isinstance(x, str) for x in cov):
            errs.append(f"topic {name!r}: video_coverage must be an array of video id strings, got {cov!r}")
            cov = []
        for x in cov:
            if x not in idset:
                errs.append(f"topic {name!r}: video_coverage names {x!r}, not in videos[]")
        entries = t.get("entries")
        if not isinstance(entries, list) or not entries:
            errs.append(f"topic {name!r}: entries missing or empty")
            entries = []
        covered = set()
        for k, e in enumerate(entries):
            if not (isinstance(e, dict) and e.get("video_id") in idset and _int(e.get("timestamp"))
                    and _str(e.get("quote"))):
                errs.append(f"topic {name!r}: entries[{k}] needs a session video_id, int timestamp, quote")
                continue
            covered.add(e["video_id"])
        if set(cov) != covered:
            errs.append(f"topic {name!r}: video_coverage {sorted(set(cov))} != videos in entries {sorted(covered)}")

    dis = a.get("disagreements")
    if not isinstance(dis, list):
        errs.append("analysis.disagreements: not an array")
        dis = []
    for i, g in enumerate(dis):
        if not isinstance(g, dict) or set(g) != DISAGREEMENT_KEYS:
            errs.append(f"disagreements[{i}]: must have exactly {sorted(DISAGREEMENT_KEYS)}, "
                        f"got {sorted(g) if isinstance(g, dict) else g!r}")
            continue
        if not _str(g["topic"]):
            errs.append(f"disagreements[{i}]: topic empty")
        pos = g["positions"]
        if not isinstance(pos, list) or len(pos) < 2:
            errs.append(f"disagreements[{i}]: positions must be an array of at least two")
            continue
        for k, p in enumerate(pos):
            if not isinstance(p, dict) or set(p) != POSITION_KEYS:
                errs.append(f"disagreements[{i}].positions[{k}]: must be exactly {{video_id, position}}")
            elif p["video_id"] not in idset or not _str(p["position"]):
                errs.append(f"disagreements[{i}].positions[{k}]: unknown video or empty position")

    # key_moments and workflow_steps are separate arrays and are never merged.
    km = a.get("key_moments")
    if not isinstance(km, list):
        errs.append("analysis.key_moments: not an array")
        km = []
    for i, k in enumerate(km):
        if not isinstance(k, dict) or set(k) != KEY_MOMENT_KEYS:
            extra = sorted(set(k) - KEY_MOMENT_KEYS) if isinstance(k, dict) else []
            errs.append(f"key_moments[{i}]: must be exactly {sorted(KEY_MOMENT_KEYS)}"
                        + (f" (carries step fields {extra}: merged with workflow_steps?)" if extra else ""))
            continue
        if k["video_id"] not in idset:
            errs.append(f"key_moments[{i}]: unknown video {k['video_id']!r}")
        if not _int(k["timestamp"]) or k["timestamp"] < 0:
            errs.append(f"key_moments[{i}]: timestamp must be a non-negative int")
        if not (_str(k["label"]) and _str(k["description"])):
            errs.append(f"key_moments[{i}]: label and description required")

    steps = a.get("workflow_steps", [])
    if not isinstance(steps, list):
        errs.append("analysis.workflow_steps: not an array")
        steps = []
    per_video = {}
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            errs.append(f"workflow_steps[{i}]: not an object")
            continue
        tag = f"step {s.get('video_id')}#{s.get('index')}"
        keys = set(s)
        if keys != set(STEP_KEYS):
            errs.append(f"{tag}: fields must be exactly the 15; missing {sorted(set(STEP_KEYS) - keys)}, "
                        f"extra {sorted(keys - set(STEP_KEYS))}")
        vid = s.get("video_id")
        if vid not in idset:
            errs.append(f"{tag}: video_id not in videos[]")
        idx = s.get("index")
        if not _int(idx):
            errs.append(f"{tag}: index must be an int")
        per_video.setdefault(vid, []).append(idx)
        ts, te = s.get("t_start"), s.get("t_end")
        if not (_int(ts) and _int(te)):
            errs.append(f"{tag}: t_start and t_end must be ints")
        elif ts < 0 or te <= ts:
            errs.append(f"{tag}: span t_start={ts} t_end={te} (need 0 <= t_start < t_end)")
        if _int(ts) and vid in chapters_by_id:
            want = chapter_covering(chapters_by_id[vid], ts)
            if s.get("phase") != want:
                errs.append(f"{tag}: phase {s.get('phase')!r} != chapter covering t_start {want!r}")
        if not _str(s.get("action")):
            errs.append(f"{tag}: action empty")
        if s.get("app") not in APPS:
            errs.append(f"{tag}: app {s.get('app')!r} not in {sorted(APPS)}")
        up = s.get("ui_path")
        if not (isinstance(up, list) and all(isinstance(x, str) for x in up)):
            errs.append(f"{tag}: ui_path must be an array of strings")
        kind = s.get("ui_kind")
        if kind not in UI_KINDS:
            errs.append(f"{tag}: ui_kind {kind!r} not in {sorted(UI_KINDS)}")
        if not isinstance(s.get("ui_target"), str):
            errs.append(f"{tag}: ui_target must be a string")
        opts = s.get("ui_options")
        if not (isinstance(opts, list) and all(isinstance(x, str) for x in opts)):
            errs.append(f"{tag}: ui_options must be an array of strings")
        elif opts and kind not in OPTION_KINDS:
            errs.append(f"{tag}: ui_options must be [] for ui_kind {kind!r}")
        prm = s.get("parameters")
        if not (isinstance(prm, dict) and all(isinstance(k, str) and isinstance(x, str) for k, x in prm.items())):
            errs.append(f"{tag}: parameters must be an object of string -> string")
        if not isinstance(s.get("result"), str):
            errs.append(f"{tag}: result must be a string")
        ref = s.get("frame_ref")
        if not _frame_ref_ok(ref):
            errs.append(f"{tag}: frame_ref must be a relative path or null, got {str(ref)[:60]!r}")
        elif ref and data_dir is not None and not (Path(data_dir) / ref).is_file():
            errs.append(f"{tag}: frame_ref {ref!r} does not exist under {data_dir}")
        conf = s.get("confidence")
        if conf not in CONFIDENCE:
            errs.append(f"{tag}: confidence {conf!r} not in {sorted(CONFIDENCE)}")
        elif conf == "shown" and not ref:
            errs.append(f"{tag}: confidence shown without a frame_ref")
    for vid, idxs in per_video.items():
        if idxs != list(range(1, len(idxs) + 1)):
            errs.append(f"{vid}: step index not 1-based contiguous in array order: {idxs[:12]}")
    if require_per_video:
        for vid in ids:
            if vid not in per_video:
                errs.append(f"{vid}: zero workflow_steps")
            if not any(isinstance(k, dict) and k.get("video_id") == vid for k in km):
                errs.append(f"{vid}: zero key_moments")

    # ---- stats ----------------------------------------------------------------
    st = data.get("stats")
    if not isinstance(st, dict):
        errs.append("stats: missing")
        st = {}
    expect = {"common_topics": len(topics), "disagreements": len(dis),
              "key_moments": len(km), "workflow_steps": len(steps)}
    for k, n in expect.items():
        if k == "workflow_steps" and k not in st and "workflow_steps" not in a:
            continue  # pre-workflow_steps session: a missing key reads as 0
        if not _int(st.get(k)) or st.get(k) != n:
            errs.append(f"stats.{k}={st.get(k)!r}, expected int {n}")
    return errs


def summarize(data):
    """Per-video counts for the report. Tolerant of malformed data."""
    a = data.get("analysis") or {} if isinstance(data, dict) else {}
    steps = [s for s in a.get("workflow_steps") or [] if isinstance(s, dict)]
    km = [k for k in a.get("key_moments") or [] if isinstance(k, dict)]
    rows = []
    for v in (data.get("videos") or []) if isinstance(data, dict) else []:
        if not isinstance(v, dict):
            continue
        vs = [s for s in steps if s.get("video_id") == v.get("id")]
        rows.append({"id": v.get("id"), "title": v.get("title"),
                     "chapters": len(v.get("chapters") or []),
                     "workflow_steps": len(vs),
                     "key_moments": sum(1 for k in km if k.get("video_id") == v.get("id")),
                     "frames": sum(1 for s in vs if s.get("frame_ref")),
                     "shown": sum(1 for s in vs if s.get("confidence") == "shown")})
    return {"videos": rows, "workflow_steps": len(steps), "key_moments": len(km),
            "topics": len(a.get("topics") or []), "disagreements": len(a.get("disagreements") or []),
            "confidence": {c: sum(1 for s in steps if s.get("confidence") == c) for c in sorted(CONFIDENCE)}}


def resolve(session):
    p = Path(session)
    if p.is_file():
        return p
    if p.is_dir():
        return p / "comparison_data.json"
    from _utils import DATA_DIR
    return DATA_DIR / "sessions" / session / "comparison_data.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--session", required=True, help="session dir, dir name, or comparison_data.json")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict")
    ap.add_argument("--check-frames", action="store_true",
                    help="also require every non-null frame_ref to exist under the data dir "
                         "(the session's grandparent: <data>/sessions/<dir>)")
    ap.add_argument("--require-per-video", action="store_true",
                    help="also require >= 1 workflow step and >= 1 key moment for every video")
    args = ap.parse_args(argv)
    try:  # titles carry em dashes; a cp1252 console would print them as mojibake
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    path = resolve(args.session)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"VALIDATE_COMPARISON unreadable: {path}: {e}", file=sys.stderr)
        return 2
    data_dir = path.parent.parent.parent if args.check_frames else None
    errs = validate(data, data_dir, args.require_per_video)
    summary = summarize(data)
    if args.json:
        print(json.dumps({"session_file": str(path), "ok": not errs, "violations": errs,
                          "summary": summary}, indent=2, ensure_ascii=False))
    else:
        print(f"session: {path}")
        for r in summary["videos"]:
            print(f"  {r['id']}  steps={r['workflow_steps']}  key_moments={r['key_moments']}  "
                  f"chapters={r['chapters']}  frames={r['frames']}  shown={r['shown']}  title={r['title']!r}")
        print(f"totals: workflow_steps={summary['workflow_steps']} key_moments={summary['key_moments']} "
              f"topics={summary['topics']} disagreements={summary['disagreements']}")
        print(f"confidence: {summary['confidence']}")
        print("VALIDATE_COMPARISON", "pass" if not errs else f"fail ({len(errs)} violations)")
        for e in errs:
            print("  -", e)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
