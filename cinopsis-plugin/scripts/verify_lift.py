#!/usr/bin/env python3
"""verify_lift.py - the lift gate and the coverage gate for Cinopsis v3.

Cinopsis carries code lifted raw from two upstream repos at pinned shas:

    claude-video  https://github.com/bradautomates/claude-video  03ceb42f...
    Agent-Reach   https://github.com/Panniantong/Agent-Reach     a19a171f...

Every lifted block is fenced:

    # >>> LIFT <repo>@<sha8> <path>:<first>-<last>
    ...upstream lines...
    # <<< LIFT

PROVENANCE GATE. For each fence the upstream file is read with
`git show <sha>:<path>` from a local clone and compared line by line with the
fenced body. A line that is equal passes. A line that differs, or that was
added, must end in a `# seam: <why>` comment. An upstream line that vanished
without a seam line standing in its place is a failure. So the fence proves the
block is upstream code, and the seam markers are the complete list of what
Cinopsis changed.

COVERAGE GATE. Every top-level function and class in the upstream source trees
must be either inside a lifted block (and is then mapped to its Cinopsis
file:line) or listed in scripts/lift_parked.json with a reason and the path of
the parked stage contract. Anything unaccounted for fails the gate.

Exit codes: 0 green, 1 red, 2 UNVERIFIED (an upstream clone is missing or at
the wrong history - the gate never fakes a pass).

    python scripts/verify_lift.py                  # both gates
    python scripts/verify_lift.py --manifest-md F  # also write the Integration Manifest table
    python scripts/verify_lift.py --json
"""
from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("scripts", "tests")
PARKED_FILE = REPO / "scripts" / "lift_parked.json"

UPSTREAMS = {
    "claude-video": {
        "dir": "claude-video",
        "sha": "03ceb42f7fa2c4439aca01752118044baabffb8f",
        "url": "https://github.com/bradautomates/claude-video",
        "source_roots": ("skills/watch/scripts/",),
    },
    "agent-reach": {
        "dir": "Agent-Reach",
        "sha": "a19a171fa980a0785849596492e0af4db800c82f",
        "url": "https://github.com/Panniantong/Agent-Reach",
        "source_roots": ("agent_reach/",),
    },
}

OPEN_RE = re.compile(r"^# >>> LIFT (?P<repo>[\w-]+)@(?P<sha>[0-9a-f]{7,40}) (?P<path>\S+):(?P<a>\d+)-(?P<b>\d+)\s*$")
CLOSE = "# <<< LIFT"
SEAM_RE = re.compile(r"#\s*seam:\s*\S")


def upstream_root() -> Path:
    return Path(os.environ.get("CINOPSIS_UPSTREAM_ROOT", Path.home() / "GriotSandbox"))


class Unverified(Exception):
    """An upstream clone is absent or does not hold the pinned sha."""


_SHOW_CACHE: dict[tuple[str, str], list[str]] = {}


def upstream_lines(repo: str, path: str) -> list[str]:
    key = (repo, path)
    if key not in _SHOW_CACHE:
        up = UPSTREAMS[repo]
        clone = upstream_root() / up["dir"]
        if not (clone / ".git").exists():
            raise Unverified(f"no clone of {repo} at {clone}")
        r = subprocess.run(["git", "-C", str(clone), "show", f"{up['sha']}:{path}"],
                           capture_output=True)
        if r.returncode != 0:
            msg = r.stderr.decode("utf-8", "replace").strip()
            if "exists on disk, but not in" in msg or "does not exist in" in msg:
                _SHOW_CACHE[key] = None  # a real answer: the path is not in that commit
            else:
                raise Unverified(f"{repo}: git show {up['sha'][:8]}:{path} failed: {msg}")
        else:
            _SHOW_CACHE[key] = r.stdout.decode("utf-8").splitlines()
    return _SHOW_CACHE[key]


def upstream_tree(repo: str) -> list[str]:
    up = UPSTREAMS[repo]
    clone = upstream_root() / up["dir"]
    r = subprocess.run(["git", "-C", str(clone), "ls-tree", "-r", "--name-only", up["sha"]],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Unverified(f"{repo}: cannot list tree at {up['sha'][:8]}")
    return [p for p in r.stdout.splitlines()
            if p.endswith(".py") and p.startswith(up["source_roots"])]


@dataclass
class Block:
    file: Path
    open_line: int          # 1-based line of the >>> fence in the Cinopsis file
    repo: str
    sha: str
    path: str
    a: int
    b: int
    body: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    seam_lines: int = 0
    verbatim_lines: int = 0

    @property
    def where(self) -> str:
        return f"{self.file.relative_to(REPO).as_posix()}:{self.open_line}"


def find_blocks() -> tuple[list[Block], list[str]]:
    blocks, errors = [], []
    for d in SCAN_DIRS:
        for f in sorted((REPO / d).rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            lines = f.read_text(encoding="utf-8").splitlines()
            cur = None
            for i, line in enumerate(lines, 1):
                m = OPEN_RE.match(line)
                if m:
                    if cur:
                        errors.append(f"{f.relative_to(REPO)}:{i}: nested LIFT fence")
                    cur = Block(f, i, m["repo"], m["sha"], m["path"], int(m["a"]), int(m["b"]))
                elif line.rstrip() == CLOSE:
                    if not cur:
                        errors.append(f"{f.relative_to(REPO)}:{i}: close fence without open")
                    else:
                        blocks.append(cur)
                        cur = None
                elif cur is not None:
                    cur.body.append(line)
            if cur:
                errors.append(f"{f.relative_to(REPO)}:{cur.open_line}: LIFT fence never closed")
    return blocks, errors


def verify_block(bl: Block) -> None:
    up = UPSTREAMS.get(bl.repo)
    if not up:
        bl.problems.append(f"unknown upstream repo {bl.repo!r}")
        return
    if not up["sha"].startswith(bl.sha):
        bl.problems.append(f"sha {bl.sha} is not the pinned {up['sha'][:8]}")
        return
    src = upstream_lines(bl.repo, bl.path)
    if src is None:
        bl.problems.append(f"{bl.path} does not exist at {up['sha'][:8]}")
        return
    if not (1 <= bl.a <= bl.b <= len(src)):
        bl.problems.append(f"range {bl.a}-{bl.b} outside {bl.path} ({len(src)} lines)")
        return
    want = src[bl.a - 1:bl.b]
    sm = difflib.SequenceMatcher(a=want, b=bl.body, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            bl.verbatim_lines += i2 - i1
            continue
        if op == "delete":
            bl.problems.append(
                f"upstream {bl.path}:{bl.a + i1}-{bl.a + i2 - 1} dropped with no seam line in its place")
            continue
        for j in range(j1, j2):
            if SEAM_RE.search(bl.body[j]):
                bl.seam_lines += 1
            else:
                local = bl.open_line + 1 + j
                bl.problems.append(f"line {local} differs from upstream without a '# seam:' marker: "
                                   f"{bl.body[j].strip()[:90]!r}")


def upstream_symbols(repo: str) -> list[dict]:
    out = []
    for path in upstream_tree(repo):
        src = upstream_lines(repo, path)
        tree = ast.parse("\n".join(src) + "\n")
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = n.decorator_list[0].lineno if n.decorator_list else n.lineno
                out.append({"repo": repo, "path": path, "name": n.name,
                            "kind": "class" if isinstance(n, ast.ClassDef) else "def",
                            "a": start, "b": n.end_lineno, "def_line": n.lineno})
    return out


def locate(sym: dict, blocks: list[Block]) -> str | None:
    for bl in blocks:
        if bl.repo == sym["repo"] and bl.path == sym["path"] and bl.a <= sym["a"] and sym["b"] <= bl.b:
            pat = re.compile(rf"^\s*(async\s+def|def|class)\s+{re.escape(sym['name'])}\b")
            for j, line in enumerate(bl.body):
                if pat.match(line):
                    return f"{bl.file.relative_to(REPO).as_posix()}:{bl.open_line + 1 + j}"
            return f"{bl.where} (definition line rewritten at a seam)"
    return None


def load_parked() -> dict:
    if not PARKED_FILE.exists():
        return {}
    return json.loads(PARKED_FILE.read_text(encoding="utf-8"))


def parked_entry(sym: dict, parked: dict) -> dict | None:
    by_path = parked.get(sym["repo"], {}).get(sym["path"])
    if not by_path:
        return None
    return by_path.get(sym["name"]) or by_path.get("*")


def run(manifest_md: Path | None = None) -> dict:
    blocks, fence_errors = find_blocks()
    for bl in blocks:
        verify_block(bl)
    parked = load_parked()
    rows, unaccounted, bad_parks = [], [], []
    for repo in UPSTREAMS:
        for sym in upstream_symbols(repo):
            where = locate(sym, blocks)
            if where:
                rows.append({**sym, "status": "lifted", "to": where})
                continue
            entry = parked_entry(sym, parked)
            if entry:
                contract = entry.get("contract", "")
                if not entry.get("reason") or not contract or not (REPO / contract).exists():
                    bad_parks.append(f"{repo}:{sym['path']}:{sym['name']} parked without reason or "
                                     f"existing contract ({contract or 'none'})")
                rows.append({**sym, "status": "not-yet", "reason": entry.get("reason", ""),
                             "contract": contract})
            else:
                unaccounted.append(f"{repo}:{sym['path']}:{sym['a']} {sym['kind']} {sym['name']}")
                rows.append({**sym, "status": "UNACCOUNTED"})
    block_problems = [f"{bl.where} [{bl.repo} {bl.path}:{bl.a}-{bl.b}] {p}" for bl in blocks for p in bl.problems]
    lifted = sum(1 for r in rows if r["status"] == "lifted")
    report = {
        "blocks": len(blocks),
        "verbatim_lines": sum(bl.verbatim_lines for bl in blocks),
        "seam_lines": sum(bl.seam_lines for bl in blocks),
        "symbols": len(rows),
        "lifted": lifted,
        "not_yet": sum(1 for r in rows if r["status"] == "not-yet"),
        "unaccounted": unaccounted,
        "fence_errors": fence_errors,
        "block_problems": block_problems,
        "bad_parks": bad_parks,
        "rows": rows,
        "block_list": [{"where": bl.where, "repo": bl.repo, "path": bl.path, "range": f"{bl.a}-{bl.b}",
                        "verbatim": bl.verbatim_lines, "seams": bl.seam_lines} for bl in blocks],
    }
    report["green"] = not (unaccounted or fence_errors or block_problems or bad_parks)
    if manifest_md:
        manifest_md.write_text(render_manifest(report), encoding="utf-8", newline="\n")
    return report


def render_manifest(rep: dict) -> str:
    out = ["# Integration Manifest - upstream symbol coverage (generated by scripts/verify_lift.py)", "",
           f"Blocks: {rep['blocks']} | verbatim lines: {rep['verbatim_lines']} | seam lines: {rep['seam_lines']} | "
           f"symbols: {rep['symbols']} | lifted: {rep['lifted']} | not-yet: {rep['not_yet']} | "
           f"unaccounted: {len(rep['unaccounted'])}", ""]
    for repo, up in UPSTREAMS.items():
        out += [f"## {repo} @ {up['sha'][:8]} ({up['url']})", "",
                "| upstream symbol | kind | status | Cinopsis home / reason | parked contract |",
                "|---|---|---|---|---|"]
        for r in rep["rows"]:
            if r["repo"] != repo:
                continue
            sym = f"`{r['path']}:{r['a']}-{r['b']}` {r['name']}"
            if r["status"] == "lifted":
                out.append(f"| {sym} | {r['kind']} | lifted | `{r['to']}` | |")
            elif r["status"] == "not-yet":
                out.append(f"| {sym} | {r['kind']} | not-yet | {r['reason']} | `{r['contract']}` |")
            else:
                out.append(f"| {sym} | {r['kind']} | **UNACCOUNTED** | | |")
        out.append("")
    out += ["## Lifted blocks", "", "| Cinopsis fence | upstream | verbatim | seams |", "|---|---|---|---|"]
    for b in rep["block_list"]:
        out.append(f"| `{b['where']}` | {b['repo']} `{b['path']}:{b['range']}` | {b['verbatim']} | {b['seams']} |")
    return "\n".join(out) + "\n"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest-md", type=Path, help="write the Integration Manifest table here")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = ap.parse_args()
    try:
        rep = run(args.manifest_md)
    except Unverified as exc:
        print(f"LIFT_UNVERIFIED: {exc}")
        return 2
    if args.json:
        print(json.dumps({k: v for k, v in rep.items() if k != "rows"}, indent=2))
    for label in ("fence_errors", "block_problems", "bad_parks", "unaccounted"):
        for item in rep[label]:
            print(f"[{label}] {item}")
    print(f"blocks={rep['blocks']} verbatim_lines={rep['verbatim_lines']} seam_lines={rep['seam_lines']} "
          f"symbols={rep['symbols']} lifted={rep['lifted']} not_yet={rep['not_yet']} "
          f"unaccounted={len(rep['unaccounted'])}")
    print("LIFT_GATE_OK" if rep["green"] else "LIFT_GATE_RED")
    return 0 if rep["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
