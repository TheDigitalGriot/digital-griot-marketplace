#!/usr/bin/env python3
"""reach_cli.py - Agent-Reach's own CLI (lifted whole into scripts/reach/cli.py), run inside Cinopsis.

    python scripts/reach_cli.py doctor | version | check-update | watch | setup | install ...
    python scripts/reach_cli.py configure --from-browser chrome --platform xueqiu
    python scripts/reach_cli.py uninstall --dry-run | skill --install | format | transcribe <url>

Everything it writes for itself (config.yaml, cookie-derived session files, managed tools)
stays under data/reach/ (reach_home(), gitignored). What it installs FOR other programs goes
where those programs look, exactly as upstream: `skill --install` into agent skill dirs,
`install` through pip/npm/pipx.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reach.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
