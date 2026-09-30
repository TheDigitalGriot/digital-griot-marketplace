# comparison_data.json — Field Reference

Auto-created by `compare_videos.py`. All fields below must be filled before launching the viewer — tabs will be empty without them.

---

## Per-Video Fields (in `videos` array)

```json
{
  "id": "VIDEO_ID",
  "title": "...",
  "summary": "1-2 sentence synopsis of what this video covers and recommends.",
  "digest": {
    "core_takeaway": "2-3 sentences stating conclusions directly.",
    "key_points": ["Specific bullet with names/numbers", "Another concrete point"],
    "why_it_matters": "Why this video is worth watching."
  },
  "chapters": [
    {
      "title": "Chapter title exactly as YouTube shows it",
      "start_time": 0,
      "end_time": 184
    }
  ]
}
```

### `chapters`
Array, machine-filled. Written by `compare_videos.py` from the chapter markers `yt-dlp` already
returns in its metadata dump, so it costs no extra network call.
```json
[
  {
    "title": "Chapter title exactly as YouTube shows it",
    "start_time": 0,
    "end_time": 184
  }
]
```

- Do NOT hand-fill and do NOT invent entries — `[]` is the correct value for a video
  that has no chapters. This is the one per-video field the preamble's "must be filled" does not
  apply to.
- `title` is a string; `start_time` and `end_time` are integers of seconds.
- Entries keep the order `yt-dlp` returns them (ascending `start_time`).
- Chapters are the source of `phase` on `analysis.workflow_steps`: the chapter whose span covers a
  step's `t_start` names that step's phase. No chapters means `phase: null`, never a guessed phase.

---

## `analysis` Object

### `unified_summary`
String. For multi-video: cross-video synthesis paragraph. For single video: overview paragraph.

### `topics`
```json
[
  {
    "name": "Descriptive topic name",
    "video_coverage": ["video_id_1", "video_id_2"],
    "consensus": "agreement|divided|skeptical",
    "entries": [
      {
        "video_id": "abc123",
        "timestamp": 125,
        "quote": "What the creator said about this topic (exact or close paraphrase)"
      }
    ]
  }
]
```
- `consensus` must be exactly one of: `"agreement"`, `"divided"`, `"skeptical"`
- At least one entry per video that covers the topic

### `disagreements`
Array. Empty (`[]`) for single-video sessions.
```json
[
  {
    "topic": "What they disagree on",
    "positions": [
      { "video_id": "abc123", "position": "Creator A's view stated neutrally" },
      { "video_id": "xyz789", "position": "Creator B's view stated neutrally" }
    ]
  }
]
```

### `key_moments`
Array. 3-5 moments per video.
```json
[
  {
    "video_id": "abc123",
    "timestamp": 342,
    "label": "Short label (3-5 words)",
    "description": "Why this moment matters"
  }
]
```

- Keeps its 3-5 cap and keeps its meaning: significance, not procedure. It answers "what mattered
  in this video". It is NOT the step list, and the two are never merged.

### `workflow_steps`
Array, uncapped. The ordered, time-spanned procedure the video demonstrates — what the operator
DOES, in sequence, in enough UI detail that a consumer can REDRAW each step rather than merely read
a description of it.
```json
[
  {
    "video_id": "abc123",
    "index": 1,
    "t_start": 184,
    "t_end": 212,
    "phase": "Chapter title covering t_start, or null",
    "action": "Imperative. What the operator DOES",
    "app": "CC5",
    "ui_path": ["Outermost menu or panel", "then inward"],
    "ui_kind": "dropdown",
    "ui_target": "The exact control, labelled as it appears on screen",
    "ui_options": ["Choice as shown", "Next choice", "In screen order"],
    "parameters": {"Field label": "value as typed"},
    "result": "What visibly changes",
    "frame_ref": "frames/abc123_184.png",
    "confidence": "shown"
  }
]
```

Exactly those fifteen fields, no more and no fewer.

- `index` is an int, 1-based and contiguous per `video_id`. This is what expresses ORDER —
  `key_moments` never did.
- `t_start` and `t_end` are ints of seconds, `t_end` strictly greater than `t_start`. A step is a
  SPAN, not a point.
- `phase` is the `videos[].chapters[]` title whose span covers `t_start`, or `null` when the video
  has no chapter there. Never a guess.
- `app` must be exactly one of: `"CC5"`, `"iClone8"`, `"Blender"`, `"other"`
- `ui_path` is the menu or panel breadcrumb, outermost first.
- `ui_kind` must be exactly one of: `"dropdown"`, `"checkbox"`, `"slider"`, `"button"`,
  `"field"`, `"menu"`, `"tab"`, `"canvas"`, `"list"`, `"radio"`, `"other"` — WHAT KIND of
  control it is, so the step can be redrawn and not merely described. "Click the dropdown" cannot
  be redrawn as a dropdown without this.
- `ui_options` carries the choices visible when the control is open, in screen order, for a
  `dropdown`, `menu`, `list` or `radio` — with the chosen one also named in `result`. `[]` for
  every other `ui_kind`.
- `parameters` is an object of string keys to string values, `{}` when none.
- `frame_ref` is a PATH relative to the data dir, conventionally
  `frames/<video_id>_<t_start>.png`, or `null` only when capture actually failed. NEVER inlined
  base64: a 12-video session is already 13.2 MB and the viewer parses the whole file client side.
- `confidence` must be exactly one of: `"spoken"`, `"shown"`, `"inferred"`
- No volume cap. A 90-minute tutorial may legitimately produce 80-150 steps. Do not sample, do not
  summarise, do not trim to a round number.
- A session written before this field existed has no `workflow_steps` key. Every consumer reads a
  missing key as `[]`.

#### `confidence` is the honesty field
Required on every step, and not decoration. `spoken` — the narrator said it. `shown` — it was read
off a captured frame. `inferred` — neither, and it is a claim.

It exists so an extraction can never silently smuggle a guess in beside an observation. An
`inferred` step is legitimate; an `inferred` step labelled `shown` is a defect.

#### The screen is a primary source, not supporting evidence
These videos show the presenter operating the UI while they talk. A frame at `t_start` is therefore
the authoritative record of what the control looked like, what it was labelled, and what was in it
— often more reliable than the narration, which says "click this dropdown" without ever naming
it. Frame capture is driven off EVERY step's `t_start`, not a sampled subset.

- Fill `ui_kind`, `ui_target`, `ui_options` and `parameters` from what the frame shows when the
  narration is silent, and mark those steps `shown`.
- No OCR happens in the plugin. Reading text off a frame is a consumer concern, not a plugin
  concern; `confidence: "shown"` is the field that records that it happened elsewhere.

---

## `stats` Object

```json
{
  "common_topics": 5,
  "disagreements": 2,
  "key_moments": 12,
  "workflow_steps": 94
}
```

All values must be integers matching the actual array lengths above.
`workflow_steps` is `len(analysis.workflow_steps)` across every video in the session, uncapped. A
session with no procedure content carries `0`, and a session written before this field existed has
no `workflow_steps` key at all, which also reads as `0`.
