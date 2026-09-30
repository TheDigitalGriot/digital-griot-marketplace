#!/usr/bin/env node
// pre-release-audit.mjs - the deterministic half of the Cinopsis closing-ceremony gate.
// Run from the repo root:  node scripts/pre-release-audit.mjs
// Exits non-zero on any failure so cinopsis-closing-ceremony can gate on it.
//
// ADAPTED FROM Prism's scripts/pre-release-audit.mjs, not transplanted. Cinopsis is a
// PYTHON plugin with no build. What was deliberately DROPPED, and why:
//   * The npm lockfile gate (Prism's step 3, `npm ci --dry-run` + workspace-member
//     reconciliation). Cinopsis has no package.json and no package-lock.json - it declares
//     its deps in requirements.txt. A conditional block that can never fire is dead code
//     that reads as coverage, so it is gone rather than guarded by an existsSync.
//   * The single-tool mirror check. Prism publishes to TWO mirrors
//     (TheDigitalGriot/prism-plugin AND digital-griot-marketplace) and both froze
//     independently. Cinopsis publishes to ONE: the shared marketplace. Checking a
//     cinopsis-plugin standalone repo would fail-closed forever on a repo that does not
//     exist, and a permanently-red gate is one everybody learns to skip.
//   * Keying off ./VERSION. Cinopsis has no VERSION file (measured: the version lives in
//     .claude-plugin/plugin.json and .claude-plugin/marketplace.json only). Prism's audit
//     fails closed when VERSION is absent, so a straight port would have reported
//     "cannot determine the target" instead of the real verdict about the mirror.
// What was ADDED, and why:
//   * Step 2 discovers scripts/verify_*.py, not scripts/verify-*.mjs. Cinopsis's invariant
//     gate is Python (scripts/verify_invariants.py, INV1-3 over the real store).
//   * Step 3 is new: local version COHERENCE. The version string lives in two files and
//     THREE places (plugin.json:version, marketplace.json:metadata.version,
//     marketplace.json:plugins[0].version). A bump that moves one and not the others
//     publishes a manifest that disagrees with its own listing.
//   * Step 5b is new: CONTENT parity, not only the version label (see its own comment).
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

let failed = 0;
const line = (mark, msg) => console.log(`[${mark}] ${msg}`);
const run = (cmd, args, opts = {}) =>
  spawnSync(cmd, args, { encoding: 'utf8', shell: process.platform === 'win32', timeout: 180000, ...opts });

// ---------------------------------------------------------------------------
// 1. Mandatory: claude plugin validate .   (trust the exit code, not output wording)
// ---------------------------------------------------------------------------
{
  const r = run('claude', ['plugin', 'validate', '.']);
  const ok = r.status === 0;
  if (!ok) failed++;
  const detail =
    (r.error && r.error.message) ||
    ((r.stdout || '') + (r.stderr || '')).trim().split('\n').filter(Boolean).pop() ||
    `nonzero exit (${r.status})`;
  line(ok ? 'PASS' : 'FAIL', `claude plugin validate .${ok ? '' : ' - ' + detail}`);
}

// ---------------------------------------------------------------------------
// 2. Discover + run every scripts/verify_*.py (Cinopsis's invariant gates are Python)
// ---------------------------------------------------------------------------
{
  const candidates = existsSync('scripts')
    ? readdirSync('scripts').filter((f) => /^verify_.*\.py$/.test(f)).sort()
    : [];
  if (candidates.length === 0) {
    // Not a pass. Cinopsis ships scripts/verify_invariants.py; finding none means either the
    // gate was deleted or this script is running from the wrong directory, and both of those
    // must be loud. An audit that silently examines nothing is the defect it exists to catch.
    failed++;
    line('FAIL', 'no scripts/verify_*.py found - the invariant gates did not run (wrong cwd, or a gate was deleted)');
  } else {
    // Resolve a Python interpreter once. A missing interpreter FAILS - "could not check" is
    // not "checked and clean".
    const PY = ['python', 'python3', 'py'].find((c) => run(c, ['--version']).status === 0);
    if (!PY) {
      failed++;
      line('FAIL', `no python interpreter on PATH - cannot run ${candidates.length} invariant gate(s)`);
    } else {
      for (const f of candidates) {
        const r = run(PY, [`scripts/${f}`]);
        const ok = r.status === 0;
        if (!ok) failed++;
        const why = r.error ? r.error.message
          : ((r.stdout || '') + (r.stderr || '')).trim().split('\n').filter(Boolean).pop() || `exit ${r.status}`;
        line(ok ? 'PASS' : 'FAIL', `scripts/${f}${ok ? '' : ' - ' + why.slice(0, 160)}`);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 3. Local version coherence - three places, two files, one truth.
// Measured on this repo: "2.8.0" appears at .claude-plugin/plugin.json:4,
// .claude-plugin/marketplace.json:5 (metadata.version) and :13 (plugins[0].version).
// plugin.json is canonical - it is what sync-to-marketplace.sh reads and publishes. A bump
// that moves it while leaving the self-hosted marketplace.json behind ships a plugin whose
// own listing contradicts it, and nothing downstream would notice.
// ---------------------------------------------------------------------------
let localVersion = null;
let pluginName = null;
{
  if (!existsSync('.claude-plugin/plugin.json')) {
    failed++;
    line('FAIL', 'no ./.claude-plugin/plugin.json - run from the Cinopsis repo root; fail-closed');
  } else {
    const pj = JSON.parse(readFileSync('.claude-plugin/plugin.json', 'utf8'));
    localVersion = pj.version;
    pluginName = pj.name;
    if (!localVersion) {
      failed++;
      line('FAIL', '.claude-plugin/plugin.json has no version field - fail-closed');
    } else if (existsSync('.claude-plugin/marketplace.json')) {
      const mj = JSON.parse(readFileSync('.claude-plugin/marketplace.json', 'utf8'));
      const seen = [
        ['metadata.version', mj.metadata?.version],
        [`plugins['${pluginName}'].version`, (mj.plugins || []).find((p) => p.name === pluginName)?.version],
      ];
      const bad = seen.filter(([, v]) => v !== localVersion);
      if (bad.length) {
        failed++;
        line('FAIL', `.claude-plugin/marketplace.json disagrees with plugin.json v${localVersion}: ${bad.map(([k, v]) => `${k}=${v ?? 'absent'}`).join(', ')}`);
      } else {
        line('PASS', `version coherent across ${seen.length + 1} local declarations at v${localVersion}`);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 4. Structural best practices (griot-agent-architect) - SCOPED to this release's changes.
// A release gate blocks on what THIS release introduces, not the repo's whole backlog;
// `claude plugin validate` above already covers whole-plugin correctness.
// ---------------------------------------------------------------------------
const walk = (dir) =>
  existsSync(dir)
    ? readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
        const p = `${dir}/${e.name}`;
        return e.isDirectory() ? walk(p) : [p];
      })
    : [];
const base =
  (run('git', ['describe', '--tags', '--abbrev=0']).stdout || '').trim() ||
  (run('git', ['rev-parse', '--verify', 'main']).status === 0 ? 'main' : '');
let changed = null;
if (base) {
  const r = run('git', ['diff', '--name-only', `${base}..HEAD`]);
  if (r.status === 0) changed = new Set(r.stdout.split('\n').map((s) => s.trim()).filter(Boolean));
}
if (changed === null) line('WARN', 'no base tag/branch to diff against - structural checks skipped (run in a repo with history)');
const inScope = (p) => changed !== null && changed.has(p);
// Structural checks report on THEIR OWN result: sharing the global counter made an earlier
// failure stamp [FAIL] on this line too, misattributing which gate broke.
const failedBeforeStructural = failed;
// A loop that examines nothing leaves the counter unchanged, which reads as a silent PASS -
// indistinguishable from "examined everything and found no problems". Count what was opened.
let scanned = 0;

// 4a. SKILL.md size - progressive disclosure (< 500 lines)
for (const p of walk('skills').filter((p) => p.endsWith('SKILL.md') && inScope(p))) {
  scanned++;
  const n = readFileSync(p, 'utf8').split('\n').length;
  if (n > 500) { failed++; line('FAIL', `${p} is ${n} lines (>500 - push detail to references/)`); }
}
// 4b. Frontmatter present on changed skills/commands/agents
for (const p of [...walk('skills').filter((p) => p.endsWith('SKILL.md')), ...walk('commands'), ...walk('agents')]
  .filter((p) => p.endsWith('.md') && inScope(p))) {
  scanned++;
  if (!readFileSync(p, 'utf8').startsWith('---')) { failed++; line('FAIL', `${p} missing YAML frontmatter`); }
}
// 4c. No hardcoded absolute plugin paths in changed skills/commands/hooks/scripts
const HARDCODED = /[A-Za-z]:\\Users\\|\/(?:Users|home)\/[^/\s"']+\//;
for (const p of [...walk('skills'), ...walk('commands'), ...walk('hooks')]
  .filter((p) => /\.(md|json|sh|js|mjs)$/.test(p) && inScope(p))) {
  scanned++;
  if (HARDCODED.test(readFileSync(p, 'utf8'))) {
    failed++;
    line('FAIL', `${p} contains a hardcoded absolute path (use \${CLAUDE_PLUGIN_ROOT} / project-relative)`);
  }
}

if (scanned === 0) {
  failed++;
  line('FAIL', `structural checks scanned 0 files (scoped to ${changed ? changed.size + ' changed files' : 'skipped'}) - AUDIT_STRUCTURAL_ZERO_SCAN, not a pass`);
} else {
  line(failed === failedBeforeStructural ? 'PASS' : 'FAIL', `structural checks (scoped to ${changed.size} changed files, ${scanned} examined)`);
}

// ---------------------------------------------------------------------------
// 5. MARKETPLACE MIRROR FRESHNESS - the gate Cinopsis never had.
//
// Measured problem this closes: digital-griot-marketplace served a cinopsis-plugin/ mirror
// that had NEVER carried viewer/, and Cinopsis had no sync script anywhere, so no ceremony
// had a mirror step to run. Nothing failed while the mirror drifted.
//
// It reads the REMOTE over HTTPS, never a local working copy: a local copy proves nothing
// about what Cowork's marketplace backend actually serves, and that gap is exactly what let
// the drift survive every local check.
//
// FAIL CLOSED throughout. A network error, a 403, an unparseable body and a truncated tree
// are all FAILURES, never warnings - "cannot tell whether the mirror is current" is the
// blind spot this gate exists to close, so treating it as environmental noise would recreate
// the defect. That is the opposite call from a registry-reachability check, and it is
// deliberate.
//
// The Contents API with the raw media type is used rather than raw.githubusercontent.com:
// the raw CDN observably lags a real push by minutes, which would make this gate flake FAIL
// on a genuinely fresh mirror - and a gate that flakes is a gate people learn to ignore.
// ---------------------------------------------------------------------------
const OWNER = 'TheDigitalGriot';
const MARKET = 'digital-griot-marketplace';
const SUBDIR = pluginName ? `${pluginName}-plugin` : null;

if (!localVersion || !pluginName) {
  failed++;
  line('FAIL', 'mirror freshness skipped - no local version/name to compare against; fail-closed');
} else {
  // `gh auth token` lifts the unauthenticated 60/hr API cap to 5000/hr. Best effort - an
  // unauthenticated 403 still surfaces below as a clear FAIL, never a silent pass.
  const ghAuth = run('gh', ['auth', 'token']);
  const ghToken = ghAuth.status === 0 ? (ghAuth.stdout || '').trim() : '';

  const fetchRemote = async (url, accept) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const headers = { Accept: accept };
      if (ghToken) headers.Authorization = `Bearer ${ghToken}`;
      const res = await fetch(url, { signal: controller.signal, headers });
      if (!res.ok) return { error: `HTTP ${res.status} fetching ${url}` };
      return { body: await res.text() };
    } catch (e) {
      return { error: `${e.name === 'AbortError' ? 'timed out after 15s' : e.message || String(e)} fetching ${url}` };
    } finally {
      clearTimeout(timer);
    }
  };
  const contentsUrl = (repo, path) => `https://api.github.com/repos/${OWNER}/${repo}/contents/${path}?ref=main`;

  // 5a. VERSION LABEL - both places the mirror declares it.
  const checkVersion = async (label, url, extract) => {
    const r = await fetchRemote(url, 'application/vnd.github.raw+json');
    if (r.error) { failed++; line('FAIL', `${label} - could not read remote version (${r.error}) - fail-closed`); return; }
    let version;
    try { version = extract(r.body); } catch { /* falls through */ }
    if (!version) { failed++; line('FAIL', `${label} - remote response had no readable version field - fail-closed`); }
    else if (version !== localVersion) { failed++; line('FAIL', `${label} is at v${version}, local is v${localVersion} - mirror is behind, run sh scripts/sync-to-marketplace.sh`); }
    else line('PASS', `${label} matches local v${localVersion}`);
  };

  await checkVersion(
    `${MARKET} root marketplace.json '${pluginName}' entry`,
    contentsUrl(MARKET, '.claude-plugin/marketplace.json'),
    (body) => (JSON.parse(body).plugins || []).find((p) => p.name === pluginName)?.version
  );
  await checkVersion(
    `${MARKET} ${SUBDIR}/.claude-plugin/plugin.json`,
    contentsUrl(MARKET, `${SUBDIR}/.claude-plugin/plugin.json`),
    (body) => JSON.parse(body).version
  );

  // 5b. CONTENT PARITY - because a matching version label is not a synced mirror.
  //
  // This is the half that matters most here. Cinopsis's mirror has repeatedly carried the
  // CORRECT version number over an INCOMPLETE tree: an absent viewer/ (which breaks
  // compare_server.py at runtime, not merely thins the mirror), missing transcript rungs,
  // and a skills/ directory short of the source. Every version check in the world reports
  // PASS on that. So assert the set of paths instead: every blob `git archive HEAD $DIRS`
  // would emit must exist in the mirror.
  //
  // The dir list is READ OUT OF scripts/sync-to-marketplace.sh rather than repeated here.
  // One home per fact: two copies of the list is a drift waiting to happen, and it would
  // drift in the worst possible direction - a gate that checks fewer dirs than the sync
  // ships is a gate that cannot see the thing it guards.
  const SYNC = 'scripts/sync-to-marketplace.sh';
  const syncSrc = existsSync(SYNC) ? readFileSync(SYNC, 'utf8') : '';
  const dirMatch = syncSrc.match(/^MIRROR_DIRS="([^"]+)"/m);
  if (!dirMatch) {
    failed++;
    line('FAIL', `could not read MIRROR_DIRS from ${SYNC} - cannot determine what the mirror should contain; fail-closed`);
  } else {
    const dirs = dirMatch[1].split(/\s+/).filter(Boolean);
    // `git ls-tree -r HEAD -- <dirs>` filtered to blobs is what `git archive HEAD <dirs>`
    // emits: archive skips gitlinks (type commit) the same way, and this repo declares no
    // .gitattributes, so no export-ignore can make the two disagree. If one is ever added,
    // the guard below stops this check from quietly measuring the wrong set.
    if (existsSync('.gitattributes') && /export-ignore/.test(readFileSync('.gitattributes', 'utf8'))) {
      failed++;
      line('FAIL', '.gitattributes declares export-ignore - git ls-tree no longer equals git archive; teach this check to shell out to `git archive | tar -t`');
    }
    const lt = run('git', ['ls-tree', '-r', 'HEAD', '--', ...dirs]);
    const sourcePaths = (lt.stdout || '')
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.includes(' blob '))
      .map((l) => l.split('\t')[1])
      .filter(Boolean)
      .sort();

    const tree = await fetchRemote(
      `https://api.github.com/repos/${OWNER}/${MARKET}/git/trees/main?recursive=1`,
      'application/vnd.github+json'
    );
    if (tree.error) {
      failed++;
      line('FAIL', `${MARKET} ${SUBDIR}/ content parity - could not read the remote tree (${tree.error}) - fail-closed`);
    } else {
      let parsed = null;
      try { parsed = JSON.parse(tree.body); } catch { /* handled */ }
      if (!parsed || !Array.isArray(parsed.tree)) {
        failed++;
        line('FAIL', `${MARKET} ${SUBDIR}/ content parity - remote tree was unreadable - fail-closed`);
      } else if (parsed.truncated) {
        // GitHub truncates very large trees. A partial listing would manufacture phantom
        // "missing" paths; refusing is the only honest answer.
        failed++;
        line('FAIL', `${MARKET} tree response was TRUNCATED - cannot prove content parity - fail-closed`);
      } else {
        const prefix = `${SUBDIR}/`;
        const mirror = new Set(
          parsed.tree.filter((e) => e.type === 'blob' && e.path.startsWith(prefix)).map((e) => e.path.slice(prefix.length))
        );
        const missing = sourcePaths.filter((p) => !mirror.has(p));
        const extra = [...mirror].filter((p) => !sourcePaths.includes(p)).sort();
        if (missing.length) {
          failed++;
          line('FAIL', `${MARKET} ${SUBDIR}/ is missing ${missing.length} of ${sourcePaths.length} source paths - the version label can match while the tree does not:`);
          for (const p of missing) console.log(`         - ${p}`);
          console.log(`         fix: sh ${SYNC}`);
        } else {
          line('PASS', `${MARKET} ${SUBDIR}/ carries all ${sourcePaths.length} source paths (dirs: ${dirs.join(' ')})`);
        }
        // Reported, not failed: the sync replaces the subdir wholesale, so extras are stale
        // leftovers that the next real sync removes on its own.
        if (extra.length) line('INFO', `${SUBDIR}/ also carries ${extra.length} path(s) absent from the source (stale; the next sync removes them): ${extra.slice(0, 5).join(', ')}${extra.length > 5 ? ' ...' : ''}`);
      }
    }
  }
}

console.log(`\n${failed === 0 ? 'AUDIT CLEAN' : failed + ' AUDIT FAILURE(S)'}`);
process.exit(failed === 0 ? 0 : 1);
