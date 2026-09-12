#!/usr/bin/env python3
"""Idempotent, resumable per-video transcript cache.

Fetch many video IDs SAFELY: one ID per fetch is cheap (~5-10s) and fits the
~60s device-bridge cap, so a big list never times out. Already-cached IDs are
skipped; a progress file is written so a killed call resumes exactly where it
stopped. Then assemble a session from the cache with:
    compare_videos.py --urls <ids...> --from-cache

Usage:
    python fetch_transcripts.py --ids ID1 ID2 ID3 ...        # fetch up to --chunk
    python fetch_transcripts.py --ids ID1 ID2 --chunk 4      # cap per call
    python fetch_transcripts.py --ids ID1 --refresh          # force re-fetch
"""
import argparse
import json
import time
from pathlib import Path

from _utils import DATA_DIR
from get_transcript import fetch_transcript, save_transcript


def is_cached(video_id):
    return (DATA_DIR / f"transcript_{video_id}.json").exists()


def main():
    ap = argparse.ArgumentParser(description="Batch / resumable transcript cache")
    ap.add_argument("--ids", nargs="+", required=True, help="YouTube video IDs")
    ap.add_argument("--chunk", type=int, default=5,
                    help="Max IDs to fetch this call (default 5; HARD-CAPPED at 5 — anti-hammer)")
    ap.add_argument("--refresh", action="store_true", help="Re-fetch even if cached")
    args = ap.parse_args()

    # HARD ANTI-HAMMER CAP: never fetch more than 5 IDs per invocation, no matter
    # what --chunk says. This is structural so a bad driver/loop cannot burst the IP.
    MAX_CHUNK = 5
    THROTTLE_SEC = 5  # minimum gap between individual fetches within a call
    effective_chunk = max(1, min(args.chunk, MAX_CHUNK))
    if args.chunk > MAX_CHUNK:
        print(f"[cap] --chunk {args.chunk} clamped to {MAX_CHUNK} (hard anti-hammer cap)", flush=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    progress_file = DATA_DIR / "fetch_progress.json"

    todo = [v for v in args.ids if args.refresh or not is_cached(v)]
    cached_before = [v for v in args.ids if not args.refresh and is_cached(v)]
    batch = todo[:effective_chunk]

    print(f"{len(args.ids)} ids | {len(cached_before)} already cached | "
          f"{len(todo)} to fetch | this call: {len(batch)}", flush=True)

    results = {}
    for idx, vid in enumerate(batch):
        if idx > 0:
            time.sleep(THROTTLE_SEC)  # space fetches so a batch is a drip, not a burst
        print(f"\n== {vid} ==", flush=True)
        t, lang, method = fetch_transcript(vid, allow_cache=not args.refresh, refresh=args.refresh)
        if t:
            save_transcript(vid, t)
            results[vid] = {"ok": True, "entries": len(t), "method": method}
            print(f"  cached {vid}: {len(t)} entries via {method}", flush=True)
        else:
            results[vid] = {"ok": False}
            print(f"  FAILED {vid}", flush=True)

    remaining = [v for v in todo if v not in batch]
    cached_now = [v for v in args.ids if is_cached(v)]
    progress = {
        "total": len(args.ids),
        "cached": cached_now,
        "remaining": remaining,
        "last_batch": results,
    }
    progress_file.write_text(json.dumps(progress, indent=2), encoding="utf-8")

    print(f"\nDONE this call. cached={len(cached_now)}/{len(args.ids)} remaining={len(remaining)}", flush=True)
    if remaining:
        print(f"Resume: python fetch_transcripts.py --ids {' '.join(remaining)}", flush=True)
    else:
        print(f"All cached. Assemble: compare_videos.py --urls {' '.join(args.ids)} --from-cache", flush=True)


if __name__ == "__main__":
    main()
