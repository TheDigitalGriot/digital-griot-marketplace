---
name: cinopsis
description: Browse subscribed YouTube channels, fetch transcripts, and generate summary digests in Markdown. Also supports multi-video comparison — cross-video analysis with interactive dashboard, frame screenshots, and agentic chat. Use this skill whenever the user mentions "YouTube videos", "video digest", "summarize YouTube", "video summary", "youtube digest", "latest videos", "compare these videos", "compare video X and Y", "what's the difference between these videos", "cross-video analysis", "recap videos", "catch up on videos", "new videos in this playlist", "what's been added to this playlist", "ingest a playlist", "fetch playlist videos", or wants to browse, summarize, or compare YouTube content on any topic (AI, 3D modeling, coding, etc.).
---

# YouTube Video Digest

Browse subscribed YouTube channels, fetch transcripts, and generate Markdown summary digests. Works with any topic.

**Plugin root:** `${CLAUDE_PLUGIN_ROOT}` | **Data:** `${CLAUDE_PLUGIN_DATA}`

> **Stuck Protocol (device/cloud recovery — non-negotiable):** if any device/cloud tool returns empty/`[]`/"not connected"/"no DOM"/403 or fails first-call, do NOT report it blocked. Retry 2-3x -> switch surface (built-in pane <-> Claude-in-Chrome; native Windows PowerShell when the sandbox has no route; the Gmail *browser* when the *connector* is the wrong account) -> replay the logs (session_info -> last successful run -> copy its exact tool sequence) -> then ask Gavin ONE direct question. Gavin's word about his own machine is GROUND TRUTH. "Blocked" without those steps is a DEFINED ERROR; a forced skip = INCOMPLETE run. Full ladder: this plugin's CLAUDE.md "Stuck Protocol" section.
## Quick Commands (token-efficient — bypass skill loading for known operations)

- `/digest <url>` — single video analysis + viewer launch
- `/compare <url1> <url2> [url3...]` — cross-video analysis + viewer
- `/fetch [--days N] [--keyword TOPIC] [--all]` — channel video listing
- `/playlist <url|list_id> [--name NAME] [--all] [--seed] [--max-new N] [--cookies PATH]` — surface newly-added playlist videos

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
python scripts/fetch_playlist.py <url|list_id>      # new playlist videos, PACED (default 12/run; --max-new N); seeds on first sight; --all / --seed
python scripts/fetch_playlist.py <url|list_id> --cookies cookies.txt   # PRIVATE/unlisted playlist (see reachability note)
python scripts/compare_videos.py --urls URL1 [URL2 ...]
python scripts/build_session_from_analysis.py --input analysis.json --thumbnails  # inject a finished analysis (no fetch)
python scripts/compare_server.py --port 5123 --session SESSION_ID   # self-reaps after --idle-timeout (default 1800s)
python scripts/digest_all.py --days 3 --limit 10
python scripts/get_transcript.py --video-id VIDEO_ID
```

**Output locations:**
- Videos: `${CLAUDE_PLUGIN_DATA}/videos.json`
- Transcripts: `${CLAUDE_PLUGIN_DATA}/transcript_VIDEO_ID.txt`
- Digest: `${CLAUDE_PLUGIN_DATA}/output/ai_digest_YYYYMMDD.md`
- Schema ref: `${CLAUDE_PLUGIN_ROOT}/skills/cinopsis/references/comparison-schema.md`

**Inject-analysis method** (`build_session_from_analysis.py`): when transcripts were fetched + analyzed *elsewhere* — device-side while the cloud has no YouTube egress, by subagents, or any external pipeline — feed a finished-analysis JSON (same shape as `comparison-schema.md`) to build a real session through the plugin's own `save_session`/persist, then launch the viewer. Decouples analysis from fetching; `--thumbnails` backfills thumbnails (non-fatal).

## MCP Tools (Claude Cowork + Code)

On Cowork there is no Bash tool, so the same operations run through a local-stdio MCP server (`.mcp.json`) that auto-bootstraps a venv in `${CLAUDE_PLUGIN_DATA}` — zero setup. On Cowork, call these tools instead of the scripts:

- `fetch_videos(days, keyword, include_all)` — list recent channel videos
- `fetch_playlist(url, name, playlist_end, include_all, seed_only, cookies)` — surface newly-added playlist videos (returns the new-id array; `cookies` reaches private/unlisted playlists)
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
| "Ingest new videos from this playlist" | `fetch_playlist.py <url>` |
| "What's been added to this playlist?" | `fetch_playlist.py <url>` |
| "Create a digest" | `digest_all.py`, generate summaries |
| "Summarize this video: URL" | `digest-writer` → `compare_videos.py --urls URL` |
| "Summarize video #3" (from list) | `digest-writer` → `compare_videos.py --urls URL` |
| "Show all videos, no filter" | `fetch_videos.py --days 3 --all` |
| "Compare these: URL1, URL2" | `video-comparator` → `compare_videos.py --urls URL1 URL2` |
| "What do they disagree on?" | Reference disagreements in comparison data |
| "Capture the chart at 4:21" | `capture_frames.py` for that timestamp |

## Channels Config

Edit `${CLAUDE_PLUGIN_ROOT}/data/channels.json` — array of `{"name": "...", "id": "CHANNEL_ID"}` objects.


## Playlist reachability — private / unlisted playlists

`fetch_playlist.py` does a public flat-playlist scan. YouTube hands yt-dlp an empty
"playlist does not exist" for a **private or unlisted** playlist it can't see
unauthenticated, so the script returns 0 entries and prints a hint. Two ways in:

1. **cookies.txt (preferred, non-interactive).** Export a `cookies.txt` (Netscape format)
   from the logged-in browser — the "Get cookies.txt LOCALLY" Chrome extension — then
   `--cookies <path>`. Auto-discovery: if `--cookies` is omitted, it uses `$CINOPSIS_COOKIES`,
   else `data/cookies.txt` if present. On **Windows use the exported file**, not
   `--cookies-from-browser chrome`: that fails with "Failed to decrypt with DPAPI" against
   Chrome's App-Bound Encryption (yt-dlp #10927). Threaded into the yt-dlp `--flat-playlist`
   call as `--cookies`, mirroring the transcript ladder's cookie handling.
2. **Agent-side Chrome scrape (interactive fallback).** If cookies aren't handy, drive the
   logged-in Chrome to the playlist and read the entries off the page — proven pulling a
   private 1,703-video playlist end-to-end.

## Transcript fetch - the reliable ladder (cloud <-> local) [PINNED]

Fetching a transcript is environment-sensitive. `get_transcript.py` / `fetch_transcript()`
run this ladder automatically; when you drive it by hand, follow the same order. **Do not
re-derive this every session - it is baked into the tool and pinned here.**

0. **Probe with ONE video first**, and never assume egress - this sandbox may or may not have
   YouTube network access (it is inconsistent per session).
1. **cache** - reuse `data/transcript_<id>.json` if present (idempotent).
2. **api** (preferred) - `youtube-transcript-api`, instance `YouTubeTranscriptApi().fetch(id)`
   (shim: legacy static `.get_transcript(id)`). Fast, no yt-dlp; needs egress.
3. **yt-dlp** - subtitle download with cookie fallbacks. Works where the API is proxy-blocked.
   Run it with the **venv** python (`mcp_launcher.py` installs `yt-dlp` from requirements) -
   a bare system python will `FileNotFound` on yt-dlp.
4. **asr** (optional) - `yt-dlp` audio -> `faster-whisper`, for caption-LESS videos. Fires
   only if `faster-whisper` is installed; enable with `pip install faster-whisper`.
5. **Chrome caption-scrape** (agent-side) - if all else fails and you have a browser, read
   `ytInitialPlayerResponse.captions.playerCaptionsTracklistRenderer.captionTracks` off the
   loaded watch page.

### Batch / many videos - never all-N at once

**Playlists enforce this structurally:** `fetch_playlist.py` surfaces at most `--max-new N` (default 12, env `CINOPSIS_MAX_NEW_PER_RUN`) net-new per run and drains a big backlog a bounded batch at a time - the channel path's `--playlist-end 10`, applied to playlists. Never lift the cap to clear a backlog in one shot (that is the IP-block cause); let it drain over days, or run it on a daily schedule.

Fetch **one/-few IDs per call** with `fetch_transcripts.py --ids ... --chunk N` (each cheap,
fits the ~60s device-bridge cap), then assemble once with `compare_videos.py --urls ... --from-cache`.
A killed call resumes from `fetch_progress.json`. A single `compare_videos` over many URLs at
once **will time out**.

### Device gotchas (Windows-MCP bridge) - hard rules
- **Never `Start-Process` / detached background** over the bridge -> `WinError 5` access denied.
  Use sequential chunked calls (or a Scheduled Task) and poll.
- **Controlled Folder Access** blocks the bridge from writing into connected folders (e.g. GriotMeta):
  route output via `%TEMP%` then native `Copy-Item` into place.
- Run scripts with the **venv** python (`mcp_launcher.py --selfcheck` prints it), not a bare system python.
