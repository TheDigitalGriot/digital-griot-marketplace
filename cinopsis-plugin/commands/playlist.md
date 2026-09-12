---
description: Surface newly-added videos from a YouTube playlist (id-based seen-diff)
argument-hint: <url|list_id> [--name NAME] [--playlist-end N] [--all] [--seed] [--cookies PATH]
allowed-tools: Bash, Read
model: haiku
---
List new videos from a YouTube playlist with these options: $ARGUMENTS

cd ${CLAUDE_PLUGIN_ROOT} && python scripts/fetch_playlist.py $ARGUMENTS

Display results as a clean numbered list: **title** | url. Then echo the two handoff
commands the script prints (fetch_transcripts.py, then compare_videos.py --from-cache).

**Private/unlisted playlists:** a public flat-playlist scan can't see them, so the script
returns 0 entries with a hint. To reach one, pass `--cookies <path>` to a cookies.txt exported
from the logged-in browser (the "Get cookies.txt LOCALLY" Chrome extension) — or set
`$CINOPSIS_COOKIES` / drop it at `data/cookies.txt` and omit the flag. On Windows use an exported
cookies.txt, not `--cookies-from-browser` (Chrome App-Bound Encryption / DPAPI). If the hint
still shows, use the agent-side Chrome scrape to pull the list interactively.

Do NOT summarize or analyze video content. For analysis use /digest or /compare.
