#!/usr/bin/env python3
"""watch_video.py - the Watch verb inside Cinopsis.

Runs claude-video's /watch flow (scripts/media/watch.py, lifted raw) with
Cinopsis's own seams around it:

  * working files go under DATA_DIR/watch/<timestamp>/ unless --out-dir is given
  * a Gemini key saved in Cinopsis settings (gemini_api_key) is honoured, as
    well as GEMINI_API_KEY and Watch's own ~/.config/watch/.env
  * the network step passes the ratelimit gate (the "watch" source, timedtext
    door) and its outcome is recorded, so a 429 cools the right door

Every Watch flag passes straight through:

    python scripts/watch_video.py https://youtu.be/<id> --detail efficient
    python scripts/watch_video.py <url> --engine gemini --question "what is built?"
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import DATA_DIR  # noqa: E402

DOOR = "timedtext"


def _prepare_argv(argv: list[str]) -> list[str]:
    argv = list(argv)
    if "--out-dir" not in argv:
        out = Path(DATA_DIR) / "watch" / time.strftime("%Y%m%d-%H%M%S")
        argv += ["--out-dir", str(out)]
    return argv


def _seed_gemini_key() -> None:
    if os.environ.get("GEMINI_API_KEY"):
        return
    try:
        from app_settings import load_settings
        key = load_settings().get("gemini_api_key")
    except Exception:
        key = None
    if key:
        os.environ["GEMINI_API_KEY"] = key  # this process only; never written anywhere


def run_watch(argv: list[str], capture: bool = False) -> tuple[int, str]:
    """Run the Watch verb. Returns (exit code, captured report when capture=True)."""
    from media import watch
    _seed_gemini_key()
    try:
        import ratelimit
        ratelimit.check_gate("watch", door=DOOR)
    except ImportError:
        ratelimit = None
    except Exception as exc:  # RateLimited: the door is cooling - nothing touched the network
        return 75, f"watch refused by the rate-limit gate: {exc}"
    old_argv = sys.argv
    sys.argv = ["watch"] + _prepare_argv(argv)
    buf = io.StringIO()
    code = 0
    try:
        with (contextlib.redirect_stdout(buf) if capture else contextlib.nullcontext()):
            code = watch.main() or 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if exc.code and not isinstance(exc.code, int):
            buf.write(f"\n{exc.code}\n")
            if not capture:
                print(exc.code, file=sys.stderr)
    finally:
        sys.argv = old_argv
    if ratelimit is not None:
        ratelimit.record_outcome(code == 0, buf.getvalue()[-2000:] if code else "", door=DOOR)
    return code, buf.getvalue()


def main() -> int:
    from media.runtime import configure_stdio
    configure_stdio()
    code, _ = run_watch(sys.argv[1:])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
