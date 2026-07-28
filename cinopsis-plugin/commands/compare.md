---
description: Cross-video analysis of 2+ YouTube videos with interactive viewer
argument-hint: <url1> <url2> [url3...]
allowed-tools: Bash, Read, Write, Edit
model: opus[1m]
---
Compare these YouTube videos: $ARGUMENTS

cd ${CLAUDE_PLUGIN_ROOT} first, then follow these steps:

1. `python scripts/compare_videos.py --urls $ARGUMENTS`
   Note the session directory name from the output.

2. Write `${CLAUDE_PLUGIN_DATA}/session_progress.json`:
   `{"session_dir": "SESSION_DIR", "transcripts_read": [], "status": "starting"}`

3. Read ALL transcript files from `data/sessions/SESSION_DIR/_transcripts/`.
   Load every file before beginning any analysis — 1M context holds them all.
   After each read, append to `transcripts_read` in session_progress.json.
   When all loaded, set `"status": "transcripts_read"`.

4. Read comparison_data.json, then write back ALL of these fields (viewer tabs are empty without them):
   - Each video: `summary` (1-2 sentences) and `digest` (core_takeaway, key_points, why_it_matters)
   - `analysis.unified_summary` — cross-video synthesis paragraph
   - `analysis.topics` — `{name, entries: [{video_id, timestamp, quote}], video_coverage: [ids], consensus: "agreement|divided|skeptical"}`
   - `analysis.disagreements` — `{topic, positions: [{video_id, position}]}` — state both sides neutrally
   - `analysis.key_moments` — 3-5 per video: `{video_id, timestamp, label, description}`
   - `stats` — `{common_topics: N, disagreements: N, key_moments: N}`
   Update session_progress.json: `"status": "analysis_complete"`.

5. `python scripts/compare_server.py --port 5123 --session SESSION_ID`
   On launch the server **re-promotes the working copy you just filled in (with the
   analysis) to the canonical data dir**, then serves it — so the analysis actually
   reaches the file the viewer reads. It prints `Serving viewer at <url>` (the port
   may differ if 5123 was taken — **use the printed URL**), and prints a loud
   `[warn] ... EMPTY analysis` if the analysis step was skipped.
   Update session_progress.json: `"status": "complete"`.
   Verify it's live with a session-specific check: GET `<url-base>/api/session/SESSION_ID`
   should return 200 (a stale server returns 404). Tell the user the printed URL.
   Do NOT wait for the user to ask — launch immediately after saving the JSON.
