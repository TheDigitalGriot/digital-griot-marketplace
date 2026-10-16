# Frame read-back contract (one video, or one webinar chunk, per agent)

Promoted from the CC5 batch runs (`.prism/local/cc5-batch{1..4}/READBACK-CONTRACT.md`) on 2026-10-15
(N1). The read-back is the ONLY pass that may upgrade a `workflow_steps` entry to `confidence: "shown"`;
`scripts/apply_readback.py` applies its output and re-checks every field against
[comparison-schema.md](comparison-schema.md).

## Pipeline (coordinator)

1. `python scripts/readback_sheets.py --session <session>` tiles every step's `frame_ref` into 3x3
   contact sheets plus a `manifest.json` (sheet + tile position -> step).
2. Hand each fresh-context reader ONE chunk: at most 8 sheets and the step rows on them.
3. Each reader writes `readback_<VIDEO_ID>[_p<N>].json` in the format below.
4. `python scripts/apply_readback.py --session <session> --readback-dir <dir> [--dry-run] [VIDEO_ID ...]`
   applies them and prints a per-video report. Read the report; it is the evidence for the RESULT.

## Reader input

`chunk_<VIDEO_ID>[_p<N>].json`: `sheets` (absolute paths of at most 8 contact-sheet PNGs) and `steps`
(one row per tile: `sheet`, `tile_pos` 0-8 in a 3x3 grid read left-to-right, top-to-bottom, plus the
step's index, t_start, app, action, ui_path, ui_kind, ui_target, ui_options, parameters, result).

Each tile is that step's frame downscaled to 480px wide, with `#<index> t<t_start>` burnt into a
corner. **Read each SHEET once and judge every tile on it. NEVER open a raw `frames/*.png`** (the
first batch opened 247 raw frames in one context: 595 turns, 105M cache-read tokens).

## Per-step decision

- `shown: true` ONLY if the frame VISIBLY shows the control this step operates - the panel, menu,
  button, field, dropdown or viewport target named in `action` / `ui_target` - legible enough to
  identify. A title card, a talking head, a different screen, or a generic viewport where the named
  control cannot be seen is `shown: false`. Never infer from the narration. If in doubt, false.
- When `shown` is true, fill ONLY what the frame shows:
  - `ui_target`: the exact label as printed on screen (keep the current value if none is legible).
  - `ui_kind`: exactly one of dropdown, checkbox, slider, button, field, menu, tab, canvas, list, radio, other.
  - `ui_options`: the choices visible in screen order, ONLY for a dropdown, menu, list or radio that
    is visibly OPEN. Otherwise `[]`.
  - `parameters`: string -> string, only values legible in the frame. Merged with the existing ones;
    never invent a value.
  - `ui_path`: the breadcrumb visible on screen, outermost first. Keep the existing one if none is legible.
  - `app`: exactly one of CC5, iClone8, Blender, other. Change it only if the frame proves the app
    (a title bar reading Character Creator 5 -> CC5; Character Creator 4 stays `other`).
- Downscaled text you cannot read with certainty is not legible: leave the field as it is. `shown` may
  still be true if the control is clearly identifiable, but never transcribe a value you are guessing.
- `note`: one short sentence describing what the frame actually shows, for EVERY step.

## `contradicts` - the structured verdict (REQUIRED on every step)

Answer, for every step, whether the frame **contradicts** the step: a different value on screen, a
different app, a button not yet clicked, a neighbouring step's subject, or the moment BEFORE the action.

- `contradicts`: a JSON boolean, `true` or `false`. Never omitted, never a string.
- `contradicts_reason`: a non-empty string when `contradicts` is `true`; `""` when `false`.
- **Before-action frames.** `t_start` is caption onset and narrators announce a step before doing it,
  so a frame often shows the moment BEFORE the action (drift 234). Then set `shown: false`,
  `contradicts: true`, and start `contradicts_reason` with `before-action:` (e.g. `"before-action:
  dialog not yet open; previous step's panel still on screen"`). Never relabel the step to match the frame.

The applier denies on this field, not on the wording of `note`. A `shown: true` step with
`contradicts: true` keeps its spoken/inferred confidence; a `shown: true` step with no boolean
`contradicts` is refused outright. (The regex-over-the-note it replaces missed every contradiction
phrased another way - drift "Read-back regex misses frame contradictions".)

## Output - `readback_<VIDEO_ID>[_p<N>].json`, same suffix as the chunk

    {"video_id": "<id>", "steps": [
      {"index": 1, "t_start": 12, "shown": false, "contradicts": true,
       "contradicts_reason": "before-action: menu not yet open", "note": "..."},
      {"index": 2, "t_start": 21, "shown": true, "contradicts": false, "contradicts_reason": "",
       "ui_kind": "...", "ui_target": "...", "ui_options": [], "parameters": {}, "ui_path": [],
       "app": "...", "note": "..."}
    ]}

One entry per step row in the chunk, same `index` and `t_start` (the applier refuses a mismatch).
A webinar chunk keeps `"video_id"` as the bare video id. UTF-8. Do not edit any other file, do not
touch the session JSON, no network.

## Final reply (one line, then one line per contradiction)

`<file> steps=N shown=N before_action=N contradicts=N`, then `#index tT: <reason>` per contradiction.
