---
name: cinopsis-harvest
description: Paired digest-and-frame harvest pass - digest cached transcripts AND capture the on-screen frame for every workflow step, so each harvested tool or step carries a frame_ref instead of a bare spoken name. Gate-aware (checks the YouTube "frames" rate-limit gate between batches) and resumable (a partly framed session is re-entered, never restarted). Use this whenever the user says "harvest these videos", "digest and capture frames", "harvest with screenshots", "frame every step", "capture the UI for each step", "resume the frame capture", "frames stopped partway", "only the first few frames got captured", "harvest the avatar pipeline videos", "workflow diagram source frames", or wants tools, repos, or UI steps pulled out of tutorial videos WITH the screen evidence. Prefer this over capturing frames by hand-typed timestamp.
---

# Harvest Pass - digest + frames, paired, resumable

One pass per video that does both halves of a harvest: the **digest** (what was said, which
tools were named) and the **frames** (what was on screen when it was said). Transcripts
garble names and say "click this dropdown" without ever naming it; the frame is the
authoritative record of the control. A harvest without frames is half a harvest.

**Plugin root:** `${CLAUDE_PLUGIN_ROOT}` | **Data:** `${CLAUDE_PLUGIN_DATA}`

> **Stuck Protocol (device/cloud recovery - non-negotiable):** if any device/cloud tool returns empty/`[]`/"not connected"/"no DOM"/403 or fails first-call, do NOT report it blocked. Retry 2-3x -> switch surface (built-in pane <-> Claude-in-Chrome; native Windows PowerShell when the sandbox has no route) -> replay the logs (session_info -> last successful run -> copy its exact tool sequence) -> then ask Gavin ONE direct question. Gavin's word about his own machine is GROUND TRUTH. "Blocked" without those steps is a DEFINED ERROR; a forced skip = INCOMPLETE run. Full ladder: this plugin's CLAUDE.md "Stuck Protocol" section.
>
> **A cooling frames gate is not a Stuck Protocol case.** It is a known, scheduled
> state with a defined resume path (below). Do not retry-loop against it and do not
> reset it to push through - `ratelimit.py --reset` is only for a genuinely new network.

## What this skill reuses - it defines NO moment or step model of its own

The companion already has a timeline and an important-moment system, and the schema
already separates its two notions. This skill **consumes them by their real field names
and invents nothing**. Full map with file:line: `.prism/shared/plans/cinopsis-harvest-MAP.md`.
The authority is `skills/cinopsis/references/comparison-schema.md`.

| Notion | Lives at | Fields this skill reads |
|---|---|---|
| **Workflow step** - the ordered procedure | `analysis.workflow_steps[]` | `video_id`, `index`, `t_start`, `t_end`, `phase`, `ui_kind`, `ui_target`, `ui_options`, `frame_ref`, `confidence` |
| **Key moment** - what mattered | `analysis.key_moments[]` (3-5 per video) | `video_id`, `timestamp`, `label`, `description` |
| **Phase** | `videos[].chapters[]` | `title`, `start_time`, `end_time` |

- `key_moments` and `workflow_steps` are **never merged**. A moment is significance, a
  step is procedure. Do not manufacture a moment to get a frame, and do not add a field
  to either record.
- The only field this pass **writes** into the session is `workflow_steps[].frame_ref`.
  Moments contribute timestamps to the sweep and receive no field.
- The only new field in this skill is `frame_ref` on a **harvest entry** (below), and it
  is a copy of a step's existing `frame_ref`, not a new notion.

## Why this skill exists - the defect it closes

Frame capture was already built (`capture_session_frames()`), yet harvests shipped with
a handful of hand-typed timestamps and the rest of the steps unframed. The cause was not
a frame cap - **there is no cap to raise.** The cause is the rate-limit gate:

1. `capture_frames.get_stream_url()` calls `ratelimit.check_gate("frames")` before every
   uncached frame. When a cooldown is active it raises `RateLimited`.
2. `get_stream_url()` **catches it, prints the message and returns `None`**, so
   `capture_frame()` returns `None` and the sweep counts that frame as `failed`.
3. Every remaining frame then fails the same way, instantly, with no network touched.
   A mid-pass gate trip is therefore indistinguishable from "the video has no frames",
   and `capture_session_frames()` writes `frame_ref: null` onto every step it skipped.

The fix is **gate-aware batching plus resume**: check the gate between batches, stop
cleanly when it cools, and re-enter on the next call. Never raise `BATCH_CHUNK` or the
spacing to "get more through" - that only trips the gate sooner.

## What persists when the gate trips (verified in code)

| Thing | Persisted? | Consequence |
|---|---|---|
| A captured PNG `frames/<video_id>_<int(t)>.png` | yes, on disk | `capture_frame()` returns it from cache BEFORE the gate - a re-run spends zero gate budget on it |
| `frame_ref` on a step | only if the session file is rewritten | `capture_session_frames()` mutates in memory; the CLI wrapper writes once at the END |
| Gate cooldown | yes, `ratelimit` state file | `ratelimit.status()` reports `blocked` and `seconds_left` |

The PNGs are the real checkpoint. Resume is cheap because the on-disk cache already
makes every finished frame free.

## The paired pass

Run per video, in this order. Digest first: the frame timestamps come out of it.

1. **Transcript.** `python scripts/get_transcript.py VIDEO_ID` (cached copies are
   reused; the lane rules and the headed-Chrome requirement are in this plugin's
   `CLAUDE.md`). Never fetch what `data/transcript_<id>.txt` already holds.
2. **Description.** Read `data/description_<id>.txt`. It is the authority for tool and
   repo names - captions garble them. Never ship a bare spoken name as resolved.
3. **Digest and harvest.** Write the digest entry per `.prism/shared/digest-instructions.md`
   (Core Takeaway / Key Points / Why It Matters / Harvest). For a tutorial video also fill
   `analysis.workflow_steps` per `skills/cinopsis/references/comparison-schema.md`
   (`t_start`, `ui_target`, `frame_ref`, ...).
4. **Tie each harvested tool to a workflow step - do not add a moment.** A tool named
   or shown while the operator is doing something belongs to the `workflow_steps` entry
   whose `[t_start, t_end)` span covers that second; its frame is that step's
   `frame_ref`. If no step covers the mention, add the step if it is genuinely part of
   the procedure; if it is not (an aside, a sponsor read), leave the harvest entry's
   `frame_ref` null and say "no step covers it". Never pad `key_moments` to buy a frame:
   it breaks the 3-5 significance cap (schema :92) and the stats drift silently.
5. **Frame pass.** Run it per video, never per hand-typed timestamp (next section).
6. **Write back.** Append the harvest entries with `frame_ref` (shape below), then the
   progress line `done <id>` to `.prism/shared/digest-progress.txt`.

## The frame pass

Preferred, from any surface with the MCP server: the **`harvest_frames`** tool.

```
harvest_frames(session="<session_dir_name>")
```

It calls `capture_session_frames()` for each video in `BATCH_CHUNK` (20) slices, checks
`ratelimit.status()` before every slice, and rewrites the session file after every
slice. It returns `{captured, failed, deferred, remaining, malformed, stopped_by_gate,
seconds_left, frames_dir}` plus a `warning` when the frames directory differs from the
one the viewer serves. `malformed` counts steps with no usable `video_id` or `t_start`:
they cannot be framed, are not capture failures, and should be repaired in the analysis.

CLI equivalent (no gate-aware batching - the one-shot form):

```bash
cd ${CLAUDE_PLUGIN_ROOT}
python scripts/capture_frames.py --session SESSION --json
```

Use the CLI only for a short session. For a 90-minute tutorial (80-150 steps) use the
tool, because the CLI rewrites the session once, at the end, and a gate trip mid-way
nulls every step it never reached.

### Resume is specified, not implied

A step **needs framing** when its `frame_ref` is null/absent OR its PNG is missing from
the data dir. A re-entry touches only those steps.

- `status: "partial"` / `stopped_by_gate: true` -> the gate is cooling. **Stop.** Report
  `remaining` and `seconds_left`. Do not call again before the cooldown ends; when it
  has, call `harvest_frames` again with the same session. It continues from the first
  unframed step.
- `status: "ok"` with `remaining: 0` -> the frame half is complete.
- `status: "ok"` with `remaining > 0` -> those are **genuine** capture failures (stream
  URL or ffmpeg refused with the gate open). They keep `frame_ref: null`, the only case
  the schema allows. Report them by id and `t_start`; do not retry-loop.
- `deferred` counts steps nulled only because the gate tripped inside that slice. They
  are NOT failures and must never be reported as such.

Check the gate yourself before a long pass (prints JSON, `blocked` and `seconds_left`):

```bash
python scripts/ratelimit.py
```

`blocked: true` means do the digest half now and the frame half after `seconds_left`.

## Harvest entry shape

The array on disk (`.prism/shared/harvest-<date>.json`) is a JSON array of objects.
Entries carry at least `name`, `what`, `source_video_id`; later passes added `slug`,
`stars`, `cat`, `tg`, `verified`. **Keep every existing key** and add one:

```json
{
  "name": "aval",
  "what": "One-line description, only what the transcript or description states",
  "source_video_id": "IdK9p0SxH44",
  "frame_ref": "frames/IdK9p0SxH44_184.png"
}
```

- `frame_ref` is a path relative to the data dir, built as `frames/<video_id>_<int(t)>.png`
  (the same string `frame_ref_for()` produces). **Never base64.**
- Set it only when that PNG exists. Otherwise `null`, and say why (deferred vs failed).
- Additive only. Never rewrite or drop entries already in a harvest file.
- Never invent a tool the transcript or description does not name.

## Known companion limits - read before promising a viewer result

Pass 2 mapped the companion and found defects in the existing timeline/moment system
(`cinopsis-harvest-MAP.md`, "## Broken"). They are named, not fixed, and they bound what
this skill can truthfully claim:

- **Harvested frames are not yet visible in the companion** (MAP B1, B2). PNGs land in
  `DATA_DIR/frames`; the viewer's server reads the canonical data dir and has no route
  serving `frame_ref`; the step card prints the path as text. The frames exist on disk and
  in `frame_ref` and are fully usable by a diagram consumer - just do not say "you can see
  them in the viewer".
- **User-captured frames do not persist and add synthetic moments** (B3, B4). Only the
  harvest writes frames durably.
- **The timeline draws moments, not steps** (B5).
- `harvest_frames` reports `ok` for a clean pass even when B1 applies; trust its
  `warning` field, not the status alone.

## Downstream - why the frames matter

The consumer is workflow diagrams feeding Gavin's MCP tools and addons. Current focus:
**avatar-pipeline videos** (rig, clothing, export tooling - CC5, iClone8, Blender). A
diagram can only be redrawn from `ui_kind` + `ui_options` + the frame; narration alone
yields a description, not a drawing. Frames are the evidence layer behind the diagram.

## Intent Routing

| User Says | Action |
|---|---|
| "Harvest this video" / "digest and capture frames" | paired pass: steps 1-6, `harvest_frames` for the frame half |
| "Frames stopped partway" / "resume the capture" | `harvest_frames` again on the same session (it resumes) |
| "How many frames are missing?" | `harvest_frames` result `remaining`, or count steps with null `frame_ref` |
| "Capture the chart at 4:21" | one-off `capture_frame` - the single-timestamp case, not a harvest |
| "Can we raise the frame limit?" | No cap exists; explain the gate (section above) |
| "Reset the gate" | only on a genuinely new network; otherwise wait out `seconds_left` |

## Rules

- Frame capture is **part of** the harvest pass, never an afterthought timestamp list.
- Gate state is read from `ratelimit.status()`, never inferred from a failed frame.
- Resume, never restart: do not delete `frames/` or null existing `frame_ref` values.
- Headless runs: the frame half touches YouTube (yt-dlp + ffmpeg). In a no-network
  digest run (see `digest-instructions.md` HARD RULES) do the digest half only and
  report the frame half as owed.
- Lead with content, state transcript-quality problems honestly, and never skim.
