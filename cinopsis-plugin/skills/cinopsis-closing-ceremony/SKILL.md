---
name: cinopsis-closing-ceremony
description: Run the whole Cinopsis end-of-cycle ceremony in one pass - the deterministic audit gate, then cinopsis-bookend, then cinopsis-release - instead of invoking them separately and forgetting one. Use when the user says "closing ceremony", "close out the Cinopsis release", "run the ceremonies", "wrap the release", "bookend and release", or "ship Cinopsis vX.Y.Z". Sequential and fail-fast; it adds no bypass to any sub-skill's own gates. The ceremony's whole reason for existing is that the marketplace mirror step had no ceremony to live in, so it was never run.
---

# Cinopsis Closing Ceremony

An **audit gate**, then bookend, then release - back to back, in the only order that works.

> **Stuck Protocol (device/cloud recovery - non-negotiable):** if any device/cloud tool returns empty/`[]`/"not connected"/"no DOM"/403 or fails first-call, do NOT report it blocked. Retry 2-3x -> switch surface (built-in pane <-> Claude-in-Chrome; native Windows PowerShell when the sandbox has no route) -> replay the logs (session_info -> last successful run -> copy its exact tool sequence) -> then ask Gavin ONE direct question. Gavin's word about his own machine is GROUND TRUTH. "Blocked" without those steps is a DEFINED ERROR; a forced skip = INCOMPLETE run. Full ladder: this plugin's CLAUDE.md "Stuck Protocol" section.

## Sequence - run in order, do not skip or reorder

0. **Audit gate.** `node scripts/pre-release-audit.mjs` on the pre-bump tree: `claude plugin
   validate .`, every `scripts/verify_*.py` invariant gate, local version coherence, scoped
   structural checks, and the mirror-freshness checks. **Fail-fast on everything except the mirror
   checks** - those are *expected* red here, because nothing has synced yet. Read the output; do
   not skim to the summary line.
1. **Bookend** - invoke **`cinopsis-bookend`**. Analyze the commits since the last tag, agree the
   semantic bump, move all three version declarations, write the CHANGELOG section. **The version
   is decided here** and carried into the release unchanged.
2. **Release** - invoke **`cinopsis-release`**. Commit, tag, push, sync the shared marketplace
   mirror, **re-run the audit to prove the mirror actually moved**, and create the GitHub release
   (notes only, no assets).

## What this ceremony DROPPED from `prism-closing-ceremony`, and why

| Prism phase | Status | Why |
|---|---|---|
| Phase 2 - `prism-docs-update` (VitePress sync) | **DROPPED** | Cinopsis has no docs site. Its release record is the `CHANGELOG.md` section that bookend writes, so there is no separate docs phase to run and the three-phase sequence becomes two. |
| Step 0 two-stage review (`spec-reviewer` -> `quality-reviewer`) | **OPTIONAL, not mandatory** | Those agents ship with the Prism plugin, not with Cinopsis. When Prism is installed, run them on the diff since the last tag and treat an unresolved **High** as a halt. When it is not, say so plainly and rely on the deterministic audit - never silently skip a step and report the gate clean. |
| `scripts/verify-branch-integrated.mjs` | **DROPPED as a script, KEPT as a rule** | That auto-discovered Prism gate does not exist here. The release-from-`main` discipline is enforced by `cinopsis-release` Step 0 instead. |
| `PRISM_NONINTERACTIVE` + `scripts/resolve-answer.mjs` answers file | **DROPPED** | Prism scripts. Headless behaviour is stated inline in each sub-skill: destructive steps (push, GitHub release) run only when the invoking prompt explicitly asked. |
| Native installer / build gates | **DROPPED** | Nothing is built. See `cinopsis-release`'s dropped-steps table. |
| **The marketplace mirror sync** | **KEPT, and it is the point** | See below. |

## Why this ceremony exists at all

Prism had `scripts/sync-to-marketplace.sh` and a ceremony step that ran it. **Cinopsis had neither**
- no sync script anywhere in the repo, so no ceremony could have had a mirror step. The published
`cinopsis-plugin/` mirror therefore shipped without `viewer/`, without the census skill, and short
several scripts, while every local check passed and nothing anywhere failed.

That is a **missing mechanism**, not a missed habit, and it is why the fix is this ceremony plus a
fail-closed gate rather than another line in a checklist. A rule with no gate is decoration.

## Rules

- **The gate is first and fail-fast.** An unresolved failure in Step 0 halts the ceremony. A human
  may override explicitly, and the override is written into the CHANGELOG entry - never silent.
- **Decide the version once, in bookend.** Re-deriving it in release double-increments.
- **Honor every sub-skill's gates.** `cinopsis-release` pushes, syncs a shared repo and publishes a
  GitHub release. This orchestrator adds no bypass to any of them.
- **A release is not done until the mirror is verified.** `cinopsis-release` Step 6 re-runs the
  audit after syncing. If any mirror check is still red, report `RELEASE_INCOMPLETE` and name the
  check. A sync that is not verified is exactly how the drift went unseen.
- **Release from `main`, integrating the whole branch** - never cherry-pick a commit out of one.
- **Plugin edits go through `griot-agent-architect`.** If any phase modifies plugin components
  (skills, agents, commands, hooks, the manifest), follow that skill and finish with
  `claude plugin validate .` - which Step 0's audit runs for you.

## When to use

- Any request to bookend + release Cinopsis together as one wrap-up.
- **Not** for a version-only bump or a changelog touch - invoke the single relevant skill for a
  one-phase job.
