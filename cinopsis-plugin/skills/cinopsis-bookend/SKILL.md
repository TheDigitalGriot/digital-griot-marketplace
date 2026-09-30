---
name: cinopsis-bookend
description: Close a Cinopsis development cycle - analyze the commits since the last version tag, suggest the semantic bump, move EVERY version declaration together, and write the CHANGELOG section for the new version. Use when the user says "bookend", "bump Cinopsis", "what version should this be", "close out the cycle", "prep a Cinopsis release", or before cutting a release. It decides the version ONCE and hands it to cinopsis-release; it never tags, never pushes, and never touches the marketplace mirror. The version lives in three places across two files and a bump that moves one of them is the defect this skill exists to prevent.
---

# Cinopsis Bookend

Decide the version, move every declaration of it, and write the changelog entry. Nothing else.

**Workflow**: analyze commits since the last tag -> suggest a semantic bump -> move all three
version declarations -> write the CHANGELOG section -> prove coherence with the audit.

> **Stuck Protocol (device/cloud recovery - non-negotiable):** if any device/cloud tool returns empty/`[]`/"not connected"/"no DOM"/403 or fails first-call, do NOT report it blocked. Retry 2-3x -> switch surface (built-in pane <-> Claude-in-Chrome; native Windows PowerShell when the sandbox has no route) -> replay the logs (session_info -> last successful run -> copy its exact tool sequence) -> then ask Gavin ONE direct question. Gavin's word about his own machine is GROUND TRUTH. "Blocked" without those steps is a DEFINED ERROR; a forced skip = INCOMPLETE run. Full ladder: this plugin's CLAUDE.md "Stuck Protocol" section.

## What this skill DROPPED from `prism-bookend`, and why

Cinopsis is a Python plugin with no build and no docs site. Carrying Prism's steps across would
have left instructions pointing at files that do not exist here, which is worse than having no
step at all - it reads as coverage.

| Prism step | Status in Cinopsis | Why |
|---|---|---|
| Step 3 - snapshot `PRISM-DOCUMENTATION-<v>.md` | **DROPPED**, replaced | Cinopsis has no versioned documentation file. Its release record is `CHANGELOG.md` (Keep a Changelog + SemVer, already in that format). Step 4 below writes that section instead. |
| Step 5 - sync the VitePress site via `prism-docs-update` | **DROPPED** | There is no `cinopsis-docs/` site. Nothing to sync. |
| Step 4 - `echo <v> > VERSION` | **DROPPED**, replaced | Cinopsis has **no `VERSION` file**. Measured: the version string lives only in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`. Step 3 below moves those. |
| `scripts/bump-version.py` | **DROPPED** | Cinopsis has no bump script. The bump is an explicit edit, and its completeness is *gated* rather than trusted - see Step 5. |
| `PRISM_NONINTERACTIVE` + `scripts/resolve-answer.mjs` | **DROPPED** | That answers-file machinery is a Prism script. Referencing it here would point at a file this repo does not contain. When run headless, take the version from the invoking prompt or halt - never auto-bump silently. |
| Step 6 - chain into the release | **KEPT** | Handed to `cinopsis-release`, which owns tag/push/sync/GitHub release. |

## Step 1: Analyze what changed

```bash
git describe --tags --abbrev=0          # the last released tag (e.g. v2.8.0)
git log --oneline "$(git describe --tags --abbrev=0)"..HEAD
git diff --stat "$(git describe --tags --abbrev=0)"..HEAD
```

Read the commit subjects, not just the count. Cinopsis's history uses conventional prefixes
(`feat(census):`, `fix(plugin):`, `feat(schema):`), so the bump usually reads straight off them.

## Step 2: Suggest the bump

- `feat:` present, no breaking change -> **MINOR**
- only `fix:` / `chore:` / `docs:` -> **PATCH**
- a documented breaking change to a tool signature, the MCP surface, or the on-disk store -> **MAJOR**

Present the analysis and the suggestion, and get an explicit confirmation or an override before
moving anything. Running headless: use the version given in the prompt; if none was given, **halt**
and say so. Never pick a version unattended.

## Step 3: Move EVERY version declaration together

This is the step the skill exists for. The version string appears in **three places across two
files** - measured, not assumed:

| File | Location | Note |
|---|---|---|
| `.claude-plugin/plugin.json` | `version` | **Canonical.** This is what `scripts/sync-to-marketplace.sh` reads and publishes into the shared marketplace listing. |
| `.claude-plugin/marketplace.json` | `metadata.version` | The self-hosted manifest (`source: "./"`). |
| `.claude-plugin/marketplace.json` | `plugins[0].version` | Same file, **second occurrence** - a one-match-per-file edit misses it. |

Move all three to the new version in one pass. `CHANGELOG.md` also contains the old version
string, in its `## [2.8.0]` heading - that is **history, not a declaration**. Never edit an existing
changelog heading; Step 4 adds a new one above it.

## Step 4: Write the CHANGELOG section

Add a new section at the top of the entry list, matching the existing Keep a Changelog shape:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- ...

### Fixed
- ...
```

Write it from the commits read in Step 1, in Cinopsis's existing changelog voice: name the
mechanism and what it changes for the user, not the diff.

## Step 5: Prove the bump is complete - do not eyeball it

```bash
node scripts/pre-release-audit.mjs
```

Its **version coherence** check reads all three declarations and fails if any disagrees. A partial
bump is invisible to review and obvious to that check, which is the whole reason it exists. The
mirror-freshness checks in the same run will still fail at this point - that is expected and
correct: `cinopsis-release` has not synced the mirror yet.

Also confirm the bump moved what you think it did:

```bash
git diff --stat        # expect exactly: .claude-plugin/plugin.json, .claude-plugin/marketplace.json, CHANGELOG.md
```

## Output

- Version decided **once**, stated explicitly, and carried forward to `cinopsis-release`.
- All three declarations moved; `CHANGELOG.md` has a new section.
- Nothing committed, nothing tagged, nothing pushed - those belong to `cinopsis-release`.

## Rules

1. **Suggest before bumping.** Show the commit analysis and get a confirmation or an override.
2. **Move all three declarations in one pass**, then prove it with the audit rather than by reading.
3. **Never edit an existing CHANGELOG heading.** A release adds a section; it does not rewrite one.
4. **Decide the version once.** `cinopsis-release` inherits it - re-deriving it there double-bumps.
5. **This skill does not tag, push, sync or release.** It stops at a bumped, uncommitted tree.
