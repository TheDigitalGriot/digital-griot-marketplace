---
description: Fetch recent videos from subscribed YouTube channels
argument-hint: [--days N] [--keyword TOPIC] [--all]
allowed-tools: Bash, Read
model: haiku
---
Fetch YouTube videos with these options: $ARGUMENTS

cd ${CLAUDE_PLUGIN_ROOT} && python scripts/fetch_videos.py $ARGUMENTS

Display results as a clean numbered list: **title** | channel | date | duration

Do NOT summarize or analyze video content. For analysis use /digest or /compare.
