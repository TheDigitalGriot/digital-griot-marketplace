#!/bin/sh
# sync-to-marketplace.sh - push Cinopsis's plugin dirs into the shared
# digital-griot-marketplace repo as a thin cinopsis-plugin/ folder, and upsert the
# cinopsis entry in the root marketplace.json.
#
# PORTED, NOT COPIED, from the canonical multi-tool sync:
#   <griot-meta>/digital-griot-marketplace/scripts/sync-to-marketplace.sh
# (Prism's scripts/sync-to-marketplace.sh is that same file plus a port header.)
# Three deliberate deviations from the canonical copy, all measured - see the
# missing-version guard, MIRROR_DIRS, and the forbidden-path guard below. Everything
# else is canonical behaviour: when it changes, RE-PORT it, do not re-invent it.
#
# WHY THIS SCRIPT EXISTS AT ALL (the measured defect it closes):
#   digital-griot-marketplace advertised cinopsis 2.1.9 while this repo was at 2.8.0.
#   `git log --all -- cinopsis-plugin` in the marketplace returned ZERO commits - the
#   mirror had NEVER been synced. It carried 18 of 29 scripts and no skills/ at all,
#   missing ratelimit.py (the anti-hammer gate), fetch_playlist.py, and all three panel
#   transcript rungs. Root cause: Prism had a sync script and Cinopsis had none, so no
#   ceremony ever had a mirror step to run. That is a MISSING MECHANISM, not a missed
#   habit - which is why the fix is a script AND a gate (scripts/pre-release-audit.mjs)
#   rather than another line in a checklist.
#
# WHY a shared thin marketplace repo: Claude Desktop / Cowork's remote marketplace
# backend rejects source:"." on a large tool repo and times out cloning it. Cinopsis's
# own tree carries ~88 MB in data/ alone. The marketplace stays small because every entry
# is a thin plugin-dirs-only subdir with a spec-valid relative "./<subdir>" source.
#
# Usage, from the repo root:
#   sh scripts/sync-to-marketplace.sh              # clone, replace, upsert, commit, push
#   sh scripts/sync-to-marketplace.sh --dry-run    # print exactly what WOULD be written; no network, no writes
#
# --dry-run is deliberately OFFLINE and side-effect free: it answers "what would this
# script put in the mirror", and nothing else. "Is the mirror actually current?" is a
# different question with a different owner - `node scripts/pre-release-audit.mjs`, which
# reads the REMOTE. Keeping them apart is the point: a dry run that quietly reached the
# network could not serve as a cheap pre-flight, and a freshness gate that only consulted
# a local stage would prove nothing about what Cowork actually serves.
#
# Requires: node + git on PATH; push auth (SSH/HTTPS) preconfigured for the real run.
# POSIX sh ONLY. LF endings, UTF-8 without a BOM.
set -eu
if (set -o pipefail) 2>/dev/null; then set -o pipefail; fi

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "ERR  unknown argument: $arg (expected --dry-run)" >&2; exit 2 ;;
  esac
done

MARKET_URL="${GRIOT_MARKETPLACE_URL:-git@github.com:TheDigitalGriot/digital-griot-marketplace.git}"
MARKET_REPO="TheDigitalGriot/digital-griot-marketplace"

[ -f ./.claude-plugin/plugin.json ] || { echo "ERR  no ./.claude-plugin/plugin.json - run from the Cinopsis repo root" >&2; exit 1; }

NAME=$(node -e "process.stdout.write(require('./.claude-plugin/plugin.json').name)")
VERSION=$(node -e "process.stdout.write(String(require('./.claude-plugin/plugin.json').version||''))")
DESC=$(node -e "process.stdout.write(require('./.claude-plugin/plugin.json').description||'')")
SUBDIR="${NAME}-plugin"

# DEVIATION 1 - FAIL CLOSED on a missing version.
# The canonical script falls back to ./VERSION and then to the literal "0.0.0". Cinopsis has
# NO ./VERSION file: the version lives only in .claude-plugin/plugin.json and
# .claude-plugin/marketplace.json (measured, not assumed). That fallback chain would
# therefore publish a silent "0.0.0" into the shared listing, and a wrong version LABEL in
# the marketplace is the precise shape of the drift this script exists to end. So an
# unreadable version stops the sync instead of inventing one.
[ -n "$VERSION" ] || { echo "ERR  .claude-plugin/plugin.json has no version - refusing to publish an invented one" >&2; exit 1; }

# DEVIATION 2 - the dir list carries `viewer`.
# The canonical list is `.claude-plugin skills agents commands hooks scripts`. Omitting
# viewer/ would BREAK Cinopsis in the mirror, not merely thin it: scripts/compare_server.py
# resolves `plugin_root / "viewer" / "viewer.html"` and `.../"vault.html"` at runtime
# (compare_server.py:21-22), so a mirror without viewer/ ships a comparison companion that
# answers "viewer.html not found". It is 2 tracked files - thin enough to belong here.
#
# The list is an ALLOW-list, and that is how data/ stays out: 884 files and 88 MB of runtime
# cache and sessions (only 2 tracked, and even those do not belong in a thin mirror).
# tests/, docs/ and .prism/ are likewise source-repo concerns.
MIRROR_DIRS=".claude-plugin skills agents commands hooks scripts viewer"
FORBIDDEN_DIRS="data tests docs .prism .gitnexus .superpowers"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Export ONLY the committed tree - `git archive HEAD`, never rsync of the working dir, so an
# uncommitted experiment can never reach the channel Cowork reads. Each dir is probed with
# `git cat-file -e "HEAD:$d"` first so an absent (or tracked-empty) dir cannot fail the whole
# archive on an unmatched pathspec.
STAGE="$TMP/stage"; mkdir -p "$STAGE"
DIRS=""
for d in $MIRROR_DIRS; do
  git cat-file -e "HEAD:$d" 2>/dev/null && DIRS="$DIRS $d"
done
[ -n "$DIRS" ] || { echo "ERR  none of the mirror dirs exist in HEAD - nothing to sync" >&2; exit 1; }
# shellcheck disable=SC2086
git archive HEAD $DIRS | tar -x -C "$STAGE"

# DEVIATION 3 - ASSERT the contract rather than trusting the allow-list.
# Both properties below are rules whose violation is silent, and a rule with no gate is
# decoration. Cheap to check here, invisible if it is only a comment.
( cd "$STAGE" && find . -type f | sed 's|^\./||' ) | LC_ALL=C sort > "$TMP/manifest.txt"
for d in $FORBIDDEN_DIRS; do
  if grep -q "^$d/" "$TMP/manifest.txt"; then
    echo "ERR  staged tree contains $d/ - the mirror must stay thin (see MIRROR_DIRS)" >&2
    exit 1
  fi
done
grep -q '^viewer/viewer\.html$' "$TMP/manifest.txt" || {
  echo "ERR  staged tree has no viewer/viewer.html - the mirrored comparison viewer could not render" >&2
  exit 1
}

FILE_COUNT=$(wc -l < "$TMP/manifest.txt" | tr -d ' ')

if [ "$DRY_RUN" -eq 1 ]; then
  echo "DRY-RUN  $NAME v$VERSION -> $MARKET_REPO/$SUBDIR/   (nothing cloned, nothing written, nothing pushed)"
  echo "DRY-RUN  dirs archived from HEAD:$DIRS"
  echo "DRY-RUN  $FILE_COUNT files would be written under $SUBDIR/:"
  sed "s|^|  $SUBDIR/|" "$TMP/manifest.txt"
  echo "DRY-RUN  root .claude-plugin/marketplace.json entry that would be upserted:"
  node -e '
    const [name,sub,desc,ver]=process.argv.slice(1);
    process.stdout.write("  "+JSON.stringify({name,source:"./"+sub,description:desc,version:ver},null,2).split("\n").join("\n  ")+"\n");
  ' "$NAME" "$SUBDIR" "$DESC" "$VERSION"
  exit 0
fi

# Clone the shared marketplace SHALLOW so every OTHER tool's folder is preserved. The
# marketplace houses several tools; replacing only this subdir and upserting one manifest
# entry is what keeps this a sync rather than a takeover. Never force-push here.
git clone -q --depth 1 "$MARKET_URL" "$TMP/market"

rm -rf "$TMP/market/$SUBDIR"
mkdir -p "$TMP/market/$SUBDIR"
cp -R "$STAGE"/. "$TMP/market/$SUBDIR"/

# Upsert into the ROOT marketplace.json with a spec-valid relative "./<subdir>" source. The
# root manifest is the single listing; the subdir's own plugin.json stays as archived.
node -e '
const fs=require("fs"),p=process.argv[1],name=process.argv[2],sub=process.argv[3],desc=process.argv[4],ver=process.argv[5];
const j=JSON.parse(fs.readFileSync(p,"utf8"));
j.plugins=j.plugins||[];
const e={name,source:"./"+sub,description:desc,version:ver};
const i=j.plugins.findIndex(x=>x.name===name);
if(i>=0) j.plugins[i]=e; else j.plugins.push(e);
j.plugins.sort((a,b)=>a.name.localeCompare(b.name));
fs.writeFileSync(p,JSON.stringify(j,null,2)+"\n");
' "$TMP/market/.claude-plugin/marketplace.json" "$NAME" "$SUBDIR" "$DESC" "$VERSION"

cd "$TMP/market"
git add -A
if git diff --cached --quiet; then
  echo "OK  $NAME already up to date in $MARKET_REPO"
else
  git commit -q -m "sync: $NAME v$VERSION"
  git push -q origin HEAD
  echo "OK  $NAME v$VERSION ($FILE_COUNT files) synced -> $MARKET_REPO/$SUBDIR"
fi
