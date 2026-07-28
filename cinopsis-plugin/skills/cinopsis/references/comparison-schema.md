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
  }
}
```

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

---

## `stats` Object

```json
{
  "common_topics": 5,
  "disagreements": 2,
  "key_moments": 12
}
```

All values must be integers matching the actual array lengths above.
