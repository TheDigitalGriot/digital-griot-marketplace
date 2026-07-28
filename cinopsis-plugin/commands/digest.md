---
description: Summarize a YouTube video — fetch transcript, fill digest, launch viewer
argument-hint: <youtube-url>
allowed-tools: Bash, Read, Write, Edit
model: sonnet
---
Analyze this YouTube video: $ARGUMENTS

cd ${CLAUDE_PLUGIN_ROOT} first, then follow these steps:

1. `python scripts/compare_videos.py --urls $ARGUMENTS`
   Note the session directory name from the output.

2. Write `${CLAUDE_PLUGIN_DATA}/session_progress.json`:
   `{"session_dir": "SESSION_DIR", "transcripts_read": [], "status": "starting"}`

3. Read the FULL transcript: `data/sessions/SESSION_DIR/_transcripts/VIDEO_ID.txt`
   Do not skim. Update session_progress.json with `"transcripts_read": ["VIDEO_ID"], "status": "transcript_read"`.

4. Read comparison_data.json from the session, then write back these fields:
   - `videos[0].summary` — 1-2 sentence synopsis
   - `videos[0].digest` — `{"core_takeaway": "2-3 sentences", "key_points": ["specific bullet", "..."], "why_it_matters": "..."}`
   - `analysis.unified_summary` — single-video overview paragraph
   - `analysis.topics` — array of `{name, entries: [{video_id, timestamp (int seconds), quote}], video_coverage: [video_id], consensus: "agreement"}`
   - `analysis.key_moments` — 3-5 items: `{video_id, timestamp, label, description}`
   - `stats` — `{common_topics: N, disagreements: 0, key_moments: N}`
   Update session_progress.json: `"status": "analysis_complete"`.

5. `python scripts/compare_server.py --port 5123 --session SESSION_DIR_NAME`
   Update session_progress.json: `"status": "complete"`.
   Tell the user the viewer is at http://localhost:5123

6. Output the digest in chat:
   **Core Takeaway** — 2-3 sentences stating conclusions directly. No "This video discusses..." filler.
   **Key Points** — 3-5 bullets with specific content (tools, numbers, names)
   **Why It Matters** — why this is worth watching
   If transcript quality is poor, flag it before the digest.
