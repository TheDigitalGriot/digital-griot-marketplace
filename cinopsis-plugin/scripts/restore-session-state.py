#!/usr/bin/env python3
"""
PostCompact hook: Re-inject active session state after conversation compaction.
Reminds the model which session it was working on and what progress was made.
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
        sys.exit(0)  # Session finished — nothing to restore

    session_dir = state.get("session_dir", "unknown")
    transcripts = state.get("transcripts_read", [])

    print("cinopsis RECOVERY — incomplete session detected:")
    print(f"  Session directory: {session_dir}")
    if not transcripts:
        print("  Transcripts read: none — resume from Step 2 (read transcripts)")
    else:
        print(f"  Transcripts already read: {', '.join(transcripts)}")
        print("  Resume from: filling comparison_data.json for unread transcripts")
    print(f"  Status at compaction: {status}")
    print(f"  State file: {progress_file}")
except Exception:
    pass
