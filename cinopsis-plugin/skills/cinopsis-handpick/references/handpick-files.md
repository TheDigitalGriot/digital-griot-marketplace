# cinopsis-handpick - file map and shapes

Load on demand. Every path below is on-device under `%USERPROFILE%\GriotApps\Cinopsis`
unless named otherwise. `.prism/local/` is gitignored: these files never ship with the
plugin, so read them device-side. Shapes were read from the 2026-10-22 run; re-read the
live file before writing to it.

## Inputs

| File | What to read | Shape |
|---|---|---|
| `scripts/census_playlists.py` | args | `--json --cookies data\cookies.txt --playlist "<name>" --start-n N [--from-cache]` |
| `data/playlists.json` | the playlist NAME | `[{name, id, url, sort}]` |
| `.prism/local/census-deep-<slug>-<stamp>.json` | `playlists[].unread_entries` | top keys `generated_at, start_n, cookies_used, union_total, union_lanes, playlists`; each playlist `name, list_id, unread_entries, settled_band, contiguous, fallbacks` |
| `.prism/local/census-20*.json` | the regular census - the picker reads the newest | same shape |

## The lane (yt-run/)

| File | Role | Load-bearing detail |
|---|---|---|
| `ledger.json` | batch queue | `{batches: [{n, name, status, started, videos[], note, skipped?, skip_why?}], retry}`; video `{id, title, playlist, list_id, index}`; statuses tx-running -> tx-done -> an-running -> an-done |
| `handpicked-plan-<date>.json` | handpicked queue | `{"035": [videos], ..., "_note": "...", "_<topic>_groups": {theme: [ids]}}` |
| `picker.py` | `--next` round-robin fill (cross-playlist dedupe within a batch since 2026-10-22), `--claim`, `--set <batch> <status>`, `--tx-done`, `--count-ahead` | reads newest `census-20*.json` |
| `receiver.py` | 127.0.0.1:8777, `/next` + `/save` | `MAX_BATCH` caps the ledger length; `DEADLINE` stops it; `/next` serves the first tx-running batch's ids lacking `data/transcript_<id>.{json,txt}`; a `STOP` file stops it |
| `an-loop5.ps1`, `an-loop6.ps1` | claim -> headless yt-batch stage -> `LAND` under `land.lock` | own `$deadline`; end on `STOP` or on `tx-ended` + empty queue; heartbeat `an5-heartbeat.txt` / `an6-heartbeat.txt` carries `<batch> LANDED <sha>` |
| `build_cin_install.py` -> `cin-install.js` | browser lane installer | defines `window.__cinLoop3`; arm with `window.__cinFlag=window.__cinGen`; stop with `__cinFlag=-1`; pauses while `document.hidden`; stops itself after 3 visible panel failures in a row |

## Landing

- `.prism/shared/plans/2026-10-15-yt-batch-CONTEXT.md` - the per-batch stage contract the
  an-loops run. Decision 1 AMENDED 2026-10-22: every batch video reaches session, vault and
  Potluck; no-transcript videos land description-sourced with a `quality_flag` and a
  deferred full frames-pass entry.
- `.prism/shared/pot/land-potluck-batch.mjs --plan <dgs-definitive-plan.html> --stage <potluck-stage/yt-batch-NNN.json>`
  - idempotent, prints `LAND_POTLUCK_BATCH_OK` / `_NOOP`.

## The board

`%USERPROFILE%\GriotMeta\griot-live-artifacts\tools\fill-batch-board.mjs <data-json> <output>`
- positional only; an argument-less run fails loudly. Data keys: `HEADER, SPINE, BT, V,
LOOP_LANDED, LOOP_OWED, STATS, PROVENANCE, CLOSE` (also `LD, CHANNELS, ASKS, GATES, STAGES`).
Every BT entry carrying `ids` turns on the assigner (chips, Lock / Reset). `V` maps
`id -> [label, seconds, rows, springHits]`. Omitted keys render nothing, never the sample.

## Worked examples (2026-10-22 / 23)

- `.prism/local/census-deep-ainews-20261022T2350.json` - 700-deep AI News census.
- `.prism/local/yt-run/handpicked-plan-20261022.json` - keys 035-046 + `_jev_groups`.
- `.prism/local/batch-board-20261022-handpicked.json`, `.prism/local/batch-board-20261023-jev.json` - board data.
- `ledger.json` entries `yt-batch-034` (round-robin, one no-transcript skip) and
  `yt-batch-035` (first handpicked batch, note names Gavin's intent).
