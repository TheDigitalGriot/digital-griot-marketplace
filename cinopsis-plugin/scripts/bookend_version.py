"""Resolve the bookend version for a headless run, or refuse.

cinopsis-bookend decides the version ONCE. Interactive runs confirm it with Gavin; a headless
run (claude -p, a stage contract) cannot ask, so the version must arrive explicitly:

    python scripts/bookend_version.py --version 3.4.0
    CINOPSIS_BOOKEND_VERSION=3.4.0 python scripts/bookend_version.py

The flag wins over the env var. Output is one token line:
    BOOKEND_VERSION_OK <v> source=<flag|env> last=<tag>      exit 0
    BOOKEND_NEEDS_VERSION last=<tag>                          exit 3  (neither given - halt)
    BOOKEND_VERSION_REJECTED <v> reason=<why> last=<tag>      exit 2  (not SemVer, or not > last tag)

It never picks a version. A missing version is a halt, never an auto-bump.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
ENV = "CINOPSIS_BOOKEND_VERSION"


def parse(v: str):
    m = SEMVER.match(v.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def last_tag() -> str:
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", dest="version", default=None)
    args = ap.parse_args()

    last = last_tag()
    if args.version:
        raw, source = args.version, "flag"
    elif os.environ.get(ENV):
        raw, source = os.environ[ENV], "env"
    else:
        print(f"BOOKEND_NEEDS_VERSION last={last or 'none'}")
        return 3

    want = parse(raw)
    if want is None:
        print(f"BOOKEND_VERSION_REJECTED {raw} reason=not-semver last={last or 'none'}")
        return 2
    have = parse(last) if last else None
    if have is not None and want <= have:
        print(f"BOOKEND_VERSION_REJECTED {raw} reason=not-greater-than-last-tag last={last}")
        return 2

    v = ".".join(str(x) for x in want)
    print(f"BOOKEND_VERSION_OK {v} source={source} last={last or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
