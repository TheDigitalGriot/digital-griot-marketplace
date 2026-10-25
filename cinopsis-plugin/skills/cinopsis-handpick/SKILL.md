---
name: cinopsis-handpick
description: Handpick YouTube videos by topic or by link and ingest them as themed batches of 6 through the YT lane - deep titled census, a word-bounded topic sweep over unread titles, vault sessions and cached transcripts, dedupe against the ledger, the handpicked plan and the vault, themed batches written to the handpicked plan, a GENERATED batch board for Gavin to cut and Lock, then one batch at a time queued, armed and landed into session, vault and Potluck. Use whenever the user says "handpick videos", "batch these videos", "find all the videos about X and ingest them", "do a batch for" a topic, "ingest these links", "check the vault for X ingestions", "add another batch for" a topic, or hands over a set of YouTube links with a topic to sweep. Prefer cinopsis-census when the user only wants to LOOK at the backlog; prefer the round-robin picker when no topic or link drives the choice.
---

# Handpick - topic sweep, dedupe, themed batches, per-batch landing

Turns "find everything about X and ingest it" into numbered batches that ride the
existing YT lane (receiver -> browser panel pull -> an-loop analysis -> LAND).
Reproduces the 2026-10-22 run: batches 035-046 (Orca/PandaCode, REA/Ghidra, Jev/Laya).

**Plugin root:** `${CLAUDE_PLUGIN_ROOT}` | **Data:** `${CLAUDE_PLUGIN_DATA}`

**Resources - cloud / device resolution (plugin variant).** `${CLAUDE_PLUGIN_ROOT}/scripts/census_playlists.py`
ships with the plugin, as does `references/handpick-files.md`. The YT-lane
machinery does NOT ship: `.prism/local/` is gitignored, so `yt-run/` (picker, receiver,
an-loop5/6, cin-install.js, ledger.json, the handpicked plan) exists only on-device at
`%USERPROFILE%\GriotApps\Cinopsis\.prism\local\yt-run\`. This skill's home on-device is
`%USERPROFILE%\GriotApps\Cinopsis\skills\cinopsis-handpick\`. Everything executes
device-side (Windows-MCP PowerShell or `claude.exe -p`); Cowork has no Bash tool. If the
bridge is down, say so and stop - never simulate a sweep. File shapes and worked examples:
`references/handpick-files.md`.

> **Stuck Protocol:** empty / not connected / 403 on a device or browser tool is not
> "unavailable" - retry 2-3x, switch surface, replay the last good run, then ask ONE
> question. Full ladder: this plugin's CLAUDE.md.

## The workflow - in order, every time

**a. Resolve inputs + deep census.** Take explicit links/ids and the topic terms. Run a
DEEP titled census of the playlist that holds them, by its `data/playlists.json` NAME
(never the list id), with the **venv** python, redirected by **cmd.exe** (a PowerShell
`>` re-encodes the JSON). Write a one-line `.cmd` so the quoted name never nests inside
`cmd /c "..."`, then run it:

```
cd /d %USERPROFILE%\GriotApps\Cinopsis
%USERPROFILE%\.claude\plugins\data\cinopsis-cinopsis\venv\Scripts\python.exe scripts\census_playlists.py --json --cookies data\cookies.txt --playlist "AI News" --start-n 700 1> .prism\local\census-deep-ainews-20261022T2350.json 2> .prism\local\census-deep-ainews-20261022T2350.err
```

Go deeper than 700 when the topic is older. The name must NOT match `census-20*` -
picker.py reads the newest `census-20*.json`, and a deep census under that name would
hijack the round-robin.

**b. Sweep each topic** as a word-bounded, case-insensitive regex (`\bjev\b|\blaya\b`)
over: unread titles in the deep census AND the regular census; vault session titles
(`data/sessions/*/comparison_data.json`, repo and plugin-data); cached transcripts
(`data/transcript_*.txt`, count mentions). Report three lists per topic: **not ingested**
(with playlist + index), **already in vault** (session dir), **mentioned in transcripts**.

**c. Dedupe** on the id alone (a title is a label, never an identity) against every id in
`ledger.json` batches, every id in the handpicked plan, every vault session id.
Cross-playlist duplicates count once.

**d. Group by theme into batches of 6** (locked size). Priority is Gavin's; default is
specific/technical groups first, news/hype last. Write to
`.prism/local/yt-run/handpicked-plan-<date>.json` as zero-padded keys continuing the
ledger numbering (`"038": [{id, title, playlist, list_id, index}]`), plus a `_<topic>_groups`
map of theme -> ids and a `_note`.

**e. Render the decision as a GENERATED board.** Write board data JSON
(`.prism/local/batch-board-<stamp>-<slug>.json`: HEADER, SPINE, BT with `ids`, V, LOOP_LANDED,
LOOP_OWED, STATS, PROVENANCE, CLOSE), then in griot-live-artifacts:
`node tools/fill-batch-board.mjs <data> <out>` (positional only) and `show_widget` the
output VERBATIM. Never hand-compose a board. Gavin moves videos and presses Lock. A
dropped video moves to a later batch - never discarded unless he says discard. The board
has no Watch slot (logged as drift), so give a `https://www.youtube.com/watch?v=<id>` link
per video in chat.

**f. On lock - queue ONE batch, then arm the lane.**
1. Append the batch to `ledger.json` (`n`, `name` yt-batch-NNN, `status` tx-running,
   `started`, `videos`, `note` naming Gavin's intent). Back the ledger up first.
2. Raise `MAX_BATCH` in `receiver.py` to that batch number with a dated comment - a
   bytes-safe edit (read and write UTF-8 explicitly, never PS 5.1 `Get-Content`). Confirm
   `DEADLINE` there and `$deadline` in an-loop5/6 are still in the future; a passed
   deadline stops both silently.
3. Restart `receiver.py` (127.0.0.1:8777) with cwd `.prism\local\yt-run` and an absolute
   script path - relaunched from the repo root with a relative path it exits at once. Then
   assert exactly one listener on :8777.
4. Archive `yt-run/STOP` and `yt-run/tx-ended` if present (rename to `*.done-<date>`) -
   either one silently ends the loops.
5. Confirm an-loop5 and an-loop6 are alive (heartbeat advancing, no `an5-ended`/`an6-ended`).
6. Re-arm the browser lane in GB Chrome via the Claude in Chrome extension: if
   `window.__cinLoop3` is missing, inject `cin-install.js`; else
   `window.__cinFlag=window.__cinGen; __cinLoop3()`.
7. Tell Gavin to keep the YouTube tab in FRONT - the loop pauses while the tab is hidden.
8. The grab loop fixes its stop time when it starts. A batch queued after a loop restart
   is not grabbed once that cap passes - if the cap falls before this batch will be
   served, restart the loop again.

**g. Per batch - one check per marker, never poll.** Markers: `.prism/<batch>.DONE` and
the `<batch> LANDED <sha>` line in the an-loop heartbeat. Then rebuild + republish the
playlist Monitor, point the Companion at the batch session, refill the batch board (step e
data, statuses moved). Every batch video reaches session, vault and Potluck - a
no-transcript video lands description-sourced and flagged for a full frames pass
(yt-batch CONTEXT decision 1, amended 2026-10-22). **Between topic groups, stop** when
Gavin says he will quarterback (e.g. a `/griot-app-codex` handoff) and ask his intent
before queueing the next group.

## Intent routing

| User says | Do |
|---|---|
| "check the vault for X ingestions" | steps a-c only, report the three lists |
| "find all the videos about X and ingest them" / "do a batch for X" | a-e, then f-g on Lock |
| "ingest these links" | a (ids given) -> c -> d -> e |
| "add another batch for X" | d from the existing plan, e, then f |
| "how big is the backlog" | not this skill - cinopsis-census |
