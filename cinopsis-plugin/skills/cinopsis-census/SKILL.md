---
name: cinopsis-census
description: Read-only census of the configured YouTube playlists - how deep is the unprocessed frontier, and WHICH videos are in it. Reports a head window that GROWS ITSELF when saturated, alongside the contiguous frontier, and names every unread entry by index, id and title. Marks nothing seen, writes no manifest, fetches no transcript. Use this whenever the question is "how many videos are left in that playlist", "how far behind am I", "how big is the backlog", "what is still unprocessed", "census the playlists", "how deep is the frontier", "what have I not watched yet", "audit the playlist state", "how much of this playlist have we done", or before planning a batch of transcript fetches - a census tells you the size and the contents of the job without consuming any of it. Prefer this over fetch_playlist when the user wants to LOOK rather than INGEST, because fetch_playlist marks ids as seen and this does not.
---

# Playlist Census - read-only, and it grows its own window

Answers one question - **how deep is the unprocessed frontier in each playlist, and
which videos are in it?** - without consuming any of it.

**Plugin root:** `${CLAUDE_PLUGIN_ROOT}` | **Data:** `${CLAUDE_PLUGIN_DATA}`

> **Stuck Protocol (device/cloud recovery - non-negotiable):** if any device/cloud tool returns empty/`[]`/"not connected"/"no DOM"/403 or fails first-call, do NOT report it blocked. Retry 2-3x -> switch surface (built-in pane <-> Claude-in-Chrome; native Windows PowerShell when the sandbox has no route) -> replay the logs (session_info -> last successful run -> copy its exact tool sequence) -> then ask Gavin ONE direct question. Gavin's word about his own machine is GROUND TRUTH. "Blocked" without those steps is a DEFINED ERROR; a forced skip = INCOMPLETE run. Full ladder: this plugin's CLAUDE.md "Stuck Protocol" section.

## Census vs fetch_playlist - pick the right one

| You want to | Use | Side effect |
|---|---|---|
| LOOK at the backlog - size it, name it, plan it | **this skill** | none, ever |
| INGEST the next batch into the pipeline | `fetch_playlist.py` | marks surfaced ids **seen** |

`fetch_playlist.py` is the ingest door and it *writes* `playlist_seen.json` by design.
The census is the window: it reads the same stores and touches nothing. **Never reach
for `--seed`, `--all`, or a fetch to answer a "how many are left?" question** - that
spends the backlog to measure it.

## Run it

```bash
cd ${CLAUDE_PLUGIN_ROOT}

python scripts/census_playlists.py                       # every configured playlist
python scripts/census_playlists.py --playlist "AI News"   # one list, by its data/playlists.json name
python scripts/census_playlists.py --start-n 50           # start the head window at 50 (default 25)
python scripts/census_playlists.py --from-cache           # re-analyse the cached walk, ZERO network
python scripts/census_playlists.py --json                 # machine-readable, same numbers + entries
python scripts/census_playlists.py --cookies cookies.txt  # PRIVATE/unlisted lists
```

Run it with the **venv** python (`python scripts/mcp_launcher.py --selfcheck` prints
the path), not a bare system python - `fetch_playlist_entries` needs the pinned
`yt-dlp` that sits beside that interpreter.

Exit codes: `0` clean, `1` the seen manifest changed during the run (a defect - see
"Read-only is self-proving"), `2` an unresolvable `--playlist` name.

## The two instruments - report BOTH, always, each labelled

Neither number is right alone. This is measured, not reasoned.

### 1. THE SETTLED BAND - the reliable instrument

Measure `unread / N` over the first N entries. **If every entry in the window is
unread the head is SATURATED, and N is a FLOOR on the frontier, not a measurement of
it** - it only proves the frontier is at least N deep. So N doubles and the
measurement repeats, until `unread < N` or the list runs out. The band that finally
comes back un-saturated is the answer, and the **growth path is printed beside it**
so a floor is never mistaken for a result.

> Measured 2026-09-26: AI News read **25/25 at N=25** - saturated - and settled at
> **N=50 with 49 unread**. A fixed window reported half the frontier and presented
> the cut as the answer.

### 2. THE CONTIGUOUS FRONTIER - print it, and print that it is unreliable

The count of leading unread entries, which is also the 0-based index of the first
already-processed entry. It stops dead at that entry, so **unread entries sitting
BEHIND processed ones are invisible to it.** Always print it with the caveat
attached: it is unreliable on a **manually-sorted or cross-listed source**, and it
should be read as a floor on the untouched run at the very top of the list.

> Measured 2026-09-26: AI News contiguous **32** against a settled band of **50**.
> 3D PixelArt contiguous **5** while **13 of the first 25** are unread - 8 unread
> entries sit behind already-processed ones.

A contiguous walk under-reports an interleaved list; a fixed band under-reports a
saturated one. **Reporting one without the other is the defect this skill exists to
prevent.**

## The head is a LIST OF VIDEOS, not a count

Every unread entry inside the settled band is **named - index, id and title** - in
the text report and in `--json` alike. The titles come free from the enumeration that
has already happened (`fetch_playlist_entries` returns `{id, title, url}`), so
dropping them is a defect, not a saving. A census that says "49 unread" without
saying WHICH 49 cannot be acted on, and the caller then burns a second pass learning
what this run already knew.

**`index` is 0-based**, the same convention as the contiguous index, so the two
instruments read against each other with no off-by-one.

**A title is a LABEL, never an identity.** Every id prints beside its title, and every
membership test, dedup and diff runs on the **id alone** - creators run title tests
and one upload answers to three names within hours (drift 109). Never key anything off
a title, and never hand a bare spoken title downstream as though it resolved a video.

## The already-processed union - THREE stores, never one alone

| Lane | Store |
|---|---|
| `manifest` | `playlist_seen.json`, all playlists unioned |
| `transcripts_repo` | `transcript_*.json` **and** `transcript_*.txt` under `GriotApps\Cinopsis\data` |
| `transcripts_vault` | the same, under `.claude\plugins\data\cinopsis-cinopsis` |
| `sessions_repo` | video ids in every `sessions/*/comparison_data.json` in the repo data dir |
| `sessions_vault` | the same, under the canonical plugin data dir |

Every lane's count is printed, because **an under-counting lane inflates every unread
number and raises no error.** A lane that returns 0 while its directory plainly holds
matching files prints a loud `[WARN]` - that turns a silent wrong answer into a
visible one.

`global_seen.json` **DOES NOT EXIST** on this machine. Do not assume it, do not look
for it, do not create one.

Note the transcript lanes read **both** `.json` and `.txt`.
`fetch_playlist.seed_from_catalog()` globs only `transcript_*.json`; on this machine
the same video is often cached as `.txt` only, so a `.json`-only sweep under-counts.

## Read-only is self-proving

The script SHA-256s `playlist_seen.json` on entry and on exit, prints both, and
**exits 1 if the hash moved.** It never calls `save_seen`, never writes the manifest,
never fetches a transcript, never touches a transcript door. A census that marks
things seen is not a census. If you find a code path that would write seen-state,
that is a defect - remove it, do not gate it behind a flag.

The **only** file the census writes is the walk cache below.

## Network cost and the walk cache

Exactly **one** flat-playlist enumeration per list, through the existing
`fetch_playlist_entries` (same cookies resolution, same shared rate-limit gate). No
per-video metadata calls. No transcript calls.

The ordered id list, the titles and a timestamp are cached to
`data/_census_walk_cache.json`, so a re-analysis costs **no second scan**:
`--from-cache` re-measures from disk and touches the network zero times - the right
way to try a different `--start-n`. Cache age is always **reported**, never silently
trusted: over 24 hours prints `[STALE]`, and an unreadable timestamp prints age
UNKNOWN rather than assuming fresh.

An enumeration that returns 0 entries is reported as **UNMEASURED with its cause**
(rate-limit gate cooling, private/unlisted list without cookies, or a yt-dlp
failure) - never as a playlist that happens to have zero entries.

## Gotchas - each one returns a WRONG ANSWER rather than an error

These are measured. Every one of them is silent: no exception, no non-zero exit, just
a confident wrong number.

**(a) `_session_video_ids()` takes a `Path`, not a `str`.** Hand it a string and it
throws internally; the lane returns an **EMPTY set**, so the union under-counts and
every unread number is inflated. *Symptom:* a session lane reporting 0 while the
sessions directory is plainly full. *Measured:* vault **0 vs a real 325**, union
**283 vs a real 429**. The census constructs `Path(...)` explicitly for both lanes and
`[WARN]`s if a lane comes back empty over a populated directory.

**(b) Reading a playlist page in a browser caps at ~100 entries on initial load.**
YouTube lazy-loads the rest. *Symptom:* a suspiciously round 100. *Measured:* the
browser reported **100** for AI News against a real **2,154** from
`fetch_playlist_entries`. **Enumeration belongs to the tool, never to the browser** -
never count a playlist by reading the page.

**(c) `navigator.clipboard.writeText` from a page is blocked without user
activation.** *Symptom:* the call resolves or rejects quietly and nothing arrives.
Browser output cannot be handed back to the device that way - return it through the
tool's own stdout/JSON instead.

**(d) yt-dlp returns an EMPTY STRING - not null - for a title it could not read.**
The entry keeps its slot and its id still resolves (private, deleted, or
region-blocked), so the url derives correctly and only the **title** degrades.
*Symptom:* a named head entry with a blank where its title should be - which is
indistinguishable from the id-only projection the named head was built to remove, so
a reader cannot tell a degraded record from a broken pipeline. *Measured 2026-09-26:*
**exactly 1 of 69** named entries across the three configured lists came back
`"title": ""`, and the census passed the blank straight through. Now a blank
**declares itself** as `(title unavailable)` - parenthesised on purpose, because a
real title is never fully parenthesised and the placeholder is **never** the id
(echoing an identity into a label field is the other failure mode). It is applied
once, where the entry dict is built, so every consumer inherits it; and each playlist
carries a **`fallbacks`** integer so a degraded record is COUNTABLE, not merely
visible - `0` is a clean list. The **walk cache format does not change**: a cached
blank yields the placeholder at read time, so `--from-cache` behaves identically and
no cache rebuild is required.

## Follow-on (documented, NOT implemented) - the browser enrich lane

Per-video **title, duration, chapters and caption availability** can be read
same-origin from an already logged-in Chrome at **zero rate-limit cost** - useful for
deciding which head entries are worth a transcript before spending any door. Chunk it
under the 45 second CDP cap, about **11 videos per call**.

Not in this skill. When it is built, carry these warnings:

- A standalone `navigate()` call front-loads `tabs_context_mcp{createIfEmpty:true}`
  and **creates a visible window** on Gavin's desktop.
- Closing the group's **LAST** tab orphans that window at `about:blank` with **no
  handle left to close it**.
- And gotcha (b) above still applies: enrich per-video detail in the browser if you
  like, but never enumerate the list there.

## Intent Routing

| User Says | Action |
|---|---|
| "How many videos are left in that playlist?" | `census_playlists.py` |
| "How far behind am I?" / "how big is the backlog?" | `census_playlists.py` |
| "Which ones haven't I done?" | `census_playlists.py` (the head list names them) |
| "Census the playlists" / "audit the playlist state" | `census_playlists.py` |
| "Try that with a bigger window" | `census_playlists.py --from-cache --start-n N` |
| "Now fetch the next batch" | `fetch_playlist.py` (the ingest door - it marks seen) |

## Playlists Config

Edit `${CLAUDE_PLUGIN_ROOT}/data/playlists.json` - array of
`{"name", "id", "url", "sort"}` objects. The census reads `sort` and reports it but
never infers it: an absent or `unverified` sort means **do not trust
top-of-list-is-newest for that list**, which is exactly when the contiguous frontier
misleads and the settled band is the number to quote.
