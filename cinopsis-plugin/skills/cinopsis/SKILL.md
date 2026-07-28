---
name: cinopsis
description: Browse subscribed YouTube channels, fetch transcripts, and generate summary digests in Markdown. Also supports multi-video comparison — cross-video analysis with interactive dashboard, frame screenshots, and agentic chat. Use this skill whenever the user mentions "YouTube videos", "video digest", "summarize YouTube", "video summary", "youtube digest", "latest videos", "compare these videos", "compare video X and Y", "what's the difference between these videos", "cross-video analysis", "recap videos", "catch up on videos", or wants to browse, summarize, or compare YouTube content on any topic (AI, 3D modeling, coding, etc.).
---

# YouTube Video Digest

Browse subscribed YouTube channels, fetch transcripts, and generate Markdown summary digests. Works with any topic.

**Plugin root:** `${CLAUDE_PLUGIN_ROOT}` | **Data:** `${CLAUDE_PLUGIN_DATA}`

## Quick Commands (token-efficient — bypass skill loading for known operations)

- `/digest <url>` — single video analysis + viewer launch
- `/compare <url1> <url2> [url3...]` — cross-video analysis + viewer
- `/fetch [--days N] [--keyword TOPIC] [--all]` — channel video listing

## Agent Routing

| Task | Agent | Model |
|------|-------|-------|
| Fetch videos, list channels, simple queries | `video-fetcher` | haiku |
| Single video URL analysis, batch digests | `digest-writer` | sonnet |
| Multi-video comparison (2+ URLs) | `video-comparator` | opus[1m] |

**Single URL → `digest-writer`. Two or more URLs → `video-comparator`.** Both always launch the viewer.

## Scripts

```bash
cd ${CLAUDE_PLUGIN_ROOT}

python scripts/fetch_videos.py --days 3             # AI keyword filter
python scripts/fetch_videos.py --days 3 --all       # All topics
python scripts/fetch_videos.py --keyword "blender"  # Custom topic
python scripts/compare_videos.py --urls URL1 [URL2 ...]
python scripts/compare_server.py --port 5123 --session SESSION_ID
python scripts/digest_all.py --days 3 --limit 10
python scripts/get_transcript.py --video-id VIDEO_ID
```

**Output locations:**
- Videos: `${CLAUDE_PLUGIN_DATA}/videos.json`
- Transcripts: `${CLAUDE_PLUGIN_DATA}/transcript_VIDEO_ID.txt`
- Digest: `${CLAUDE_PLUGIN_DATA}/output/ai_digest_YYYYMMDD.md`
- Schema ref: `${CLAUDE_PLUGIN_ROOT}/skills/cinopsis/references/comparison-schema.md`

## MCP Tools (Claude Cowork + Code)

On Cowork there is no Bash tool, so the same operations run through a local-stdio MCP server (`.mcp.json`) that auto-bootstraps a venv in `${CLAUDE_PLUGIN_DATA}` — zero setup. On Cowork, call these tools instead of the scripts:

- `fetch_videos(days, keyword, include_all)` — list recent channel videos
- `get_transcript(video_id)` — fetch a transcript
- `compare_videos(urls, title)` — build a comparison session (then fill analysis + per-video digest)
- `launch_viewer(session_id, port)` — start the dashboard, returns a localhost URL to open
- `capture_frame(video_id, timestamp_seconds)` — grab a frame

Sessions auto-persist to the canonical data dir (`~/.claude/plugins/data/cinopsis-cinopsis`), so a comparison built on Cowork shows up in Claude Code and vice-versa. The session is registered at build time, and **the analysis you fill in is re-promoted to canonical when the viewer launches** (`compare_server.py` copies the working copy over before serving) — this is why you write analysis into the working `comparison_data.json`, then launch. Recover/relocate any session with `python scripts/persist_session.py <dir_name>` (or `--all`). The viewer prints `Serving viewer at <url>` — use that printed URL (the port auto-bumps if 5123 is busy).

The in-viewer chat and a ⚙ Settings panel choose the model: **Claude subscription** (default, via the claude CLI), **Anthropic API key** (fallback), or any **OpenAI-compatible local/custom endpoint** (Ollama, llama.cpp, vLLM, your fine-tunes).

## Digest Format

Output style: **digest-format**. Core Takeaway → Key Points → Why It Matters. Lead with content, no filler. Flag poor transcript quality.

## Video Analysis — Required Fields & Enforcement

Both agents fill `comparison_data.json` before launching the viewer. **The viewer tabs will be empty without all of these:**

- **Per-video `summary`** — 1-2 sentence synopsis on each video object
- **Per-video `digest`** — `core_takeaway`, `key_points`, `why_it_matters`
- **`analysis.unified_summary`** — synthesis paragraph (cross-video or single overview)
- **`analysis.topics`** — name, entries (video_id, timestamp, quote), video_coverage, consensus
- **`analysis.disagreements`** — where creators differ, both perspectives (empty array for single video)
- **`analysis.key_moments`** — 3-5 per video: video_id, timestamp, label, description
- **`stats`** — common_topics, disagreements, key_moments counts

**IMPORTANT:** Agents must complete ALL fields in a single pass and launch the viewer at the end. Do not return to the user between steps.

Frame screenshots: key moments are auto-identified; users can also click the timeline in the viewer to capture frames.

## Intent Routing

| User Says | Action |
|-----------|--------|
| "Find recent AI videos" | `fetch_videos.py --days 3` |
| "What's new in Blender?" | `fetch_videos.py --keyword "blender"` |
| "Create a digest" | `digest_all.py`, generate summaries |
| "Summarize this video: URL" | `digest-writer` → `compare_videos.py --urls URL` |
| "Summarize video #3" (from list) | `digest-writer` → `compare_videos.py --urls URL` |
| "Show all videos, no filter" | `fetch_videos.py --days 3 --all` |
| "Compare these: URL1, URL2" | `video-comparator` → `compare_videos.py --urls URL1 URL2` |
| "What do they disagree on?" | Reference disagreements in comparison data |
| "Capture the chart at 4:21" | `capture_frames.py` for that timestamp |

## Channels Config

Edit `${CLAUDE_PLUGIN_ROOT}/data/channels.json` — array of `{"name": "...", "id": "CHANNEL_ID"}` objects.
