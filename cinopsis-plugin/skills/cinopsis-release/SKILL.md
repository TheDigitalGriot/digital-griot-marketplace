---
name: cinopsis-release
description: Cut a versioned Cinopsis release - commit the bump, tag it, push, SYNC THE SHARED MARKETPLACE MIRROR, re-prove the mirror actually moved, and create a GitHub release with no build assets. Use when the user says "release Cinopsis", "cut a Cinopsis release", "ship vX.Y.Z", "publish Cinopsis", "tag the release", or "sync the marketplace". Cinopsis is a Python plugin - there are no binaries, no VSIX, no installers to build, so every Prism build step is deliberately absent. The mirror sync is NOT optional: it is the step whose absence let the published mirror ship without viewer/ and without the census skill while every local check passed.
---

# Cinopsis Release

Commit -> tag -> push -> **sync the mirror** -> **re-prove the mirror moved** -> GitHub release.

**Repository**: `TheDigitalGriot/cinopsis`
**Mirror**: `TheDigitalGriot/digital-griot-marketplace` -> `cinopsis-plugin/`

> **Stuck Protocol (device/cloud recovery - non-negotiable):** if any device/cloud tool returns empty/`[]`/"not connected"/"no DOM"/403 or fails first-call, do NOT report it blocked. Retry 2-3x -> switch surface (built-in pane <-> Claude-in-Chrome; native Windows PowerShell when the sandbox has no route) -> replay the logs (session_info -> last successful run -> copy its exact tool sequence) -> then ask Gavin ONE direct question. Gavin's word about his own machine is GROUND TRUTH. "Blocked" without those steps is a DEFINED ERROR; a forced skip = INCOMPLETE run. Full ladder: this plugin's CLAUDE.md "Stuck Protocol" section.

## What this skill DROPPED from `prism-release`, and why

Prism's release is a **build** pipeline. Cinopsis's is a **publish** pipeline. Roughly half of
`prism-release` exists only to produce a binary, and none of it applies here. Dropping it is the
point, not an omission - a step that cannot run is a step that gets skipped, and a habit of
skipping steps is how the mirror drifted in the first place.

| Prism step | Status | Why |
|---|---|---|
| 3a cross-compile CLI binaries | **DROPPED** | No Go CLI. Cinopsis is Python invoked through the plugin's MCP server and scripts. |
| 3b package VSIX | **DROPPED** | No VS Code extension. |
| 3c build Electron app | **DROPPED** | No desktop app. |
| 3d build the Tauri / NSIS installer | **DROPPED** | Nothing to install - the viewer is a Flask server started from `scripts/compare_server.py`. |
| 3e verify installers by embedded version | **DROPPED** | No installers to verify. |
| 4.5 build the Cowork sideload zip | **DROPPED** | Cowork reaches Cinopsis through the shared marketplace entry, which Step 5 below syncs. That *is* the Cowork distribution path. |
| 6b-6d upload release assets | **DROPPED** | A Cinopsis GitHub release carries **notes only**. Do not invent an asset to upload. |
| 7 eval snapshot / 8 generate eval cases | **DROPPED** | Prism-specific eval infrastructure; Cinopsis has none. |
| 6.5 sync the *single-tool* `prism-plugin` mirror | **DROPPED** | Prism has two mirrors; Cinopsis has one. There is no `TheDigitalGriot/cinopsis-plugin` repo. |
| `PRISM_NONINTERACTIVE` / `scripts/resolve-answer.mjs` gating | **DROPPED** | Prism scripts, absent here. Headless behaviour is stated inline per step instead. |
| 6.5 sync the **shared marketplace** | **KEPT AND PROMOTED** | Step 5 + Step 6 below. It is the reason this skill exists. |
| 1b validate the plugin manifest | **KEPT** | Step 1, via `node scripts/pre-release-audit.mjs`. |
| 1c clean-tree guard / 1d release-from-`main` | **KEPT** | Step 0. |

## Step 0: Pre-flight

```bash
git status --porcelain          # must be empty apart from the intended bump
git rev-parse --abbrev-ref HEAD # must be main
git describe --tags --abbrev=0  # the previous tag - the new one must not already exist
```

Release from `main`, integrating the whole branch - never cherry-pick a commit out of one. A
cherry-picked release strands the rest of the branch and drifts `main` from what actually shipped.

`cinopsis-bookend` has already decided the version and moved all three declarations. **Do not
re-derive it here** - re-running a bump double-increments. Read it back:

```bash
node -e "process.stdout.write(require('./.claude-plugin/plugin.json').version)"
```

## Step 1: Gate before anything irreversible

```bash
node scripts/pre-release-audit.mjs
```

This runs `claude plugin validate .`, every `scripts/verify_*.py` invariant gate, the local version
coherence check, the scoped structural checks, and the mirror-freshness checks. **The mirror checks
are expected to FAIL here** - the mirror has not been synced yet. Everything else must pass. If
`claude plugin validate` or an invariant gate fails, stop: do not tag a broken plugin.

## Step 2: Commit

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json CHANGELOG.md
git commit -m "v{NEW_VERSION}"
```

Add only the release files. If the tree carries unrelated work, that is a Step 0 failure, not
something to sweep into the release commit.

## Step 3: Tag

```bash
git tag v{NEW_VERSION}
```

If the tag already exists, **stop and ask**. Never delete and recreate a tag unattended - it can
clobber a real prior release. Headless: halt.

## Step 4: Push

```bash
git push origin main && git push origin v{NEW_VERSION}
```

Git writes progress to stderr and PowerShell paints it red; **that red is not a failure**. The only
success signal is ref equality:

```bash
git rev-parse HEAD; git rev-parse origin/main    # must match
```

Headless and unattended: push only when the invoking prompt explicitly asked for it. A commit and
tag that stay local are reversible; an unwanted push is not.

## Step 5: Sync the shared marketplace mirror

```bash
sh scripts/sync-to-marketplace.sh --dry-run    # read the file list first
sh scripts/sync-to-marketplace.sh              # then the real sync
```

The script clones `digital-griot-marketplace` shallow, replaces **only** `cinopsis-plugin/` with a
`git archive` of the committed tree, upserts the one `cinopsis` entry in the root
`marketplace.json`, commits and pushes. Every other tool's folder survives untouched - the
marketplace houses several tools and a sync that rewrites the repo is a defect.

**Why this step is the reason the skill exists.** Cinopsis had no sync script anywhere, so no
ceremony had a mirror step to run. The published mirror shipped without `viewer/` at all - and
`scripts/compare_server.py` resolves `plugin_root / "viewer" / "viewer.html"` at runtime, so the
comparison companion answered *"viewer.html not found"* for anyone installing from the marketplace,
while every local check passed. That was a missing mechanism, not a missed habit.

## Step 6: Re-run the gate and PROVE the mirror moved

```bash
node scripts/pre-release-audit.mjs
```

Every mirror check must now read **PASS** - both the version labels and the **content parity**
check, which asserts that every path `git archive HEAD $MIRROR_DIRS` would emit is actually present
in the mirror.

**A sync that is not verified is how the drift went unseen.** The content check is not redundant
with the version check: the mirror has carried the *correct* version number over an *incomplete*
tree before - right version, no `viewer/`, missing transcript rungs, a `skills/` directory short of
the source. A version-only gate reports PASS on exactly that state.

If a mirror check still fails, **the sync did not land**. Investigate. Do not re-run the gate
hoping it passes on its own, and do not report the release done.

## Step 7: Create the GitHub release

```bash
gh release create v{NEW_VERSION} \
  --title "Cinopsis v{NEW_VERSION}" \
  --notes-file <(sed -n '/^## \[{NEW_VERSION}\]/,/^## \[/p' CHANGELOG.md | sed '$d')
```

**No assets.** A Cinopsis release is notes plus the tag - see the dropped-steps table. Headless:
create the release only when the invoking prompt explicitly asked for it; publishing is public and
irreversible.

## Step 8: Report

State, with evidence rather than adjectives:

- the version and the tag,
- `HEAD == origin/main` (the actual sha),
- the mirror sync line (`OK cinopsis vX.Y.Z (N files) synced -> ...`),
- **the re-run audit's verdict**, quoted,
- the release URL.

A release is not done while a mirror check is red. Say `RELEASE_INCOMPLETE` and name the failing
check rather than reporting success.

## Error handling

- **`gh` not authenticated** - `gh auth login`. The audit also uses the `gh` token to lift the
  GitHub API rate cap; unauthenticated, its mirror checks may fail on a 403 rather than on drift.
- **`sync-to-marketplace.sh` refuses with "staged tree contains data/"** - a forbidden directory
  reached `MIRROR_DIRS`. Fix the list; do not weaken the guard. The mirror exists because Cowork's
  backend rejects a large clone, and `data/` alone is ~88 MB.
- **`sync-to-marketplace.sh` refuses with "no viewer/viewer.html"** - the viewer is missing from
  the committed tree. That is the runtime break the guard was written for; fix the tree.
- **`git push` rejected** - report it. Never force-push either this repo or the marketplace.
- **The audit fails on an invariant gate** - that is a real finding about the store, not release
  friction. Read `scripts/verify_invariants.py --verbose` output before deciding anything.
