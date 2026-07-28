#!/usr/bin/env python3
"""
PreCompact hook: Surface active session state before conversation compaction.
stdout is injected into the compaction summary so the model can resume correctly.
"""
import os
import json
import sys

data_dir = os.environ.get("CLAUDE_PLUGIN_DATA", "")
if not data_dir:
    sys.exit(0)

progress_file = os.path.join(data_dir, "session_progress.json")
if not os.path.exists(progress_file):
    sys.exit(0)

try:
    with open(progress_file) as f:
        state = json.load(f)

    status = state.get("status", "unknown")
    if status == "complete":
        sys.exit(0)  # Session finished — nothing to preserve

    session_dir = state.get("session_dir", "unknown")
    transcripts = state.get("transcripts_read", [])

    print("cinopsis ACTIVE SESSION — preserve in compaction summary:")
    print(f"  session_dir: {session_dir}")
    print(f"  transcripts_read: {', '.join(transcripts) if transcripts else 'none'}")
    print(f"  status: {status}")
    print(f"  state_file: {progress_file}")
    print("  IMPORTANT: Resume analysis from the status above after compaction.")
except Exception:
    pass
