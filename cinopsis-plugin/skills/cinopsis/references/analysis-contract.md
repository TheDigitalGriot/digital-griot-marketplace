# Per-video analysis contract (one video, or one webinar chunk, per agent)

Promoted from the CC5 batch runs (`.prism/local/cc5-batch{2..4}/ANALYSIS-CONTRACT.md`) on 2026-10-15
(N1). Fresh-context agents each read ONE dump and write ONE Python module; a coordinator imports the
modules and assembles `comparison_data.json`. The field law is
[comparison-schema.md](comparison-schema.md); this file is the hand-off shape around it. Frames are
judged later by the read-back ([readback-contract.md](readback-contract.md)), never here.

## Input

`dump_<VIDEO_ID>.txt`: title, channel, duration, chapters (`CH start-end title`), the description,
and the transcript (`<start_seconds> <text>`, one caption per line). Read the WHOLE dump, or the whole
time window you were assigned. Write the one module named in your task and nothing else. Do not touch
the session JSON, run network commands, or fetch anything.

## Module format (exactly this shape; the builder imports it)

```python
# <batch> analysis - <VIDEO_ID> (<title>)  [chunk <a>-<b>s when chunked]
# Source: <who narrates; voice-over or on-screen captions>. <app labelling note>
VID = "<VIDEO_ID>"
B, O, C5, I8 = "Blender", "other", "CC5", "iClone8"

SUMMARY = "1-2 sentence synopsis of what this video covers and recommends."      # whole-video agents only
DIGEST = {"core_takeaway": "2-3 sentences stating conclusions directly.",       # whole-video agents only
          "key_points": ["Specific bullet with names/numbers", "..."],
          "why_it_matters": "Why this video is worth watching (through the batch lens)."}

STEPS = [
  # (t_start, t_end, action, app, ui_path, ui_kind, ui_target, ui_options, parameters, result, confidence)
  (26, 30, "Click Restore Bind Pose on the CC timeline", O, ["Character Creator 4", "Timeline"], "button",
   "Restore Bind Pose", [], {}, "Character in the same pose as in Blender", "spoken"),
]
MOMENTS = [
  # (timestamp, label (3-5 words), description that says WHY it matters)
  (342, "Short label", "Why this moment matters, naming the panel, control and value where relevant."),
]
TOPIC_QUOTES = [
  # (timestamp, theme, "exact or close-paraphrase quote") - 6-15 of the most cross-video-relevant claims
]
NOTES = "Free text, 3-6 sentences: what the coordinator needs for the unified summary, any app-labelling calls you made, and lens findings."
```

Chunk agents omit SUMMARY and DIGEST and put what the coordinator needs for them in NOTES, unless the
task assigns one chunk (normally p1) to write them from the full dump.

## Rules

- **STEPS -> `workflow_steps`** is the ordered procedure the video DEMONSTRATES: what the operator
  DOES, in sequence, as fine-grained as the video operates. UNCAPPED: never sample, never trim to a
  round number, never fold several operations into one step.
  - Ordered by t_start, ints, `t_end > t_start` strictly (normally the next step's t_start or the end
    of the action). One video's steps never overlap backwards.
  - `app` is exactly one of CC5, iClone8, Blender, other. Character Creator 4 is `other` with
    "Character Creator 4" first in ui_path; Character Creator 5 is CC5. Version unstated -> `other`,
    said in NOTES. Never claim CC5 without evidence.
  - `ui_path` only as stated (never from your own knowledge of the tool); `[]` if nothing is stated.
  - `ui_kind` is exactly one of dropdown, checkbox, slider, button, field, menu, tab, canvas, list, radio, other.
  - `ui_options` is `[]` unless ui_kind is dropdown, menu, list or radio AND the options are stated, in order.
  - `parameters` maps string to string, values only as stated; `{}` if none.
  - `confidence` is `"spoken"` (narrator or author captions said it) or `"inferred"` (you deduced it).
    NEVER `"shown"`: nobody has looked at a frame yet. Only the read-back upgrades a step to shown.
  - Q&A or talking sections with no demonstration produce no steps. They produce moments.
- **MOMENTS -> `key_moments`** are UNCAPPED and the count follows the content. Each carries WHY it
  mattered. They are NEVER a copy of the step list: a moment marks significance (a gotcha, a ruling, a
  limitation, a number, a recommendation) and may coincide with a step while saying something different.
- **The batch lens.** Each batch names the evidence it is gathering and asks agents to capture every
  mention of it. Worked example (CC5 corpus, OA3 - the motion-engine ruling): spring bones vs Blender
  softbody/physics, baking to keyframes, rigging, weights, Data Link round trips, morphs, and FBX / GLB
  / USD export - including what does NOT survive a transfer. A Q&A answer inside the lens is a moment.
- Timestamps are the caption onset where the narrator starts describing the action.
- Plain ASCII quotes inside Python strings, escaped properly. Run `python -m py_compile <file>` before
  finishing; the module must import cleanly.
- **Chunked videos** are split by chapter into windows `[lo, hi)`. A chunk agent writes only steps and
  moments whose timestamp lies inside its window.

## Final reply (short)

Step, moment and topic-quote counts; the app labels used and why; 2-4 lines of lens findings with timestamps.
