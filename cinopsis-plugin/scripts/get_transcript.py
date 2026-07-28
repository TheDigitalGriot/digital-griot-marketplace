#!/usr/bin/env python3
"""Fetch video transcripts using yt-dlp, with proxy and cookie support."""
import json
import os
import argparse
import re
import subprocess
from pathlib import Path

from _utils import find_ytdlp, get_env, DATA_DIR


def _find_ytdlp():
    return find_ytdlp()


def get_transcript_ytdlp(video_id):
    """
    Fetch subtitles using yt-dlp with a 3-tier fallback strategy:
      1. Try without cookies (works for most public videos)
      2. Retry with Chrome cookies
      3. Retry with Firefox cookies
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = str(DATA_DIR / f"sub_{video_id}")

    ytdlp = _find_ytdlp()
    base_cmd = [
        ytdlp, "--skip-download",
        "--write-auto-sub", "--write-sub",
        "--sub-lang", "en,zh",
        "--sub-format", "vtt",
        "-o", output_template,
    ]

    print("  Attempting to fetch subtitles without cookies...", flush=True)
    subprocess.run(base_cmd + [url], capture_output=True, env=get_env(), timeout=60, stdin=subprocess.DEVNULL)

    result = _find_vtt(video_id)
    if result[0]:
        return result

    print("  Retrying with Chrome cookies...", flush=True)
    subprocess.run(
        base_cmd + ["--cookies-from-browser", "chrome", url],
        capture_output=True,
        env=get_env(),
        timeout=60,
        stdin=subprocess.DEVNULL
    )

    result = _find_vtt(video_id)
    if result[0]:
        return result

    print("  Retrying with Firefox cookies...", flush=True)
    subprocess.run(
        base_cmd + ["--cookies-from-browser", "firefox", url],
        capture_output=True,
        env=get_env(),
        timeout=60,
        stdin=subprocess.DEVNULL
    )

    return _find_vtt(video_id)


def _find_vtt(video_id):
    """Find generated subtitle files in the data directory."""
    for suffix in [".en.vtt", ".zh.vtt", ".en-orig.vtt", ".zh-Hans.vtt"]:
        sub_file = DATA_DIR / f"sub_{video_id}{suffix}"
        if sub_file.exists():
            lang = suffix.split(".")[1]
            return parse_vtt(sub_file), lang
    return None, None


def parse_vtt(vtt_file):
    """Parse a VTT subtitle file, deduplicate and merge entries."""
    content = vtt_file.read_text(encoding="utf-8")
    lines = content.split("\n")
    transcript = []
    seen_texts = set()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            parts = line.split("-->")
            start_time = parts[0].strip()
            time_parts = start_time.replace(",", ".").split(":")
            if len(time_parts) == 3:
                h, m, s = time_parts
                start_seconds = int(h) * 3600 + int(m) * 60 + float(s.split(".")[0])
            else:
                start_seconds = 0
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and "-->" not in lines[i]:
                text = lines[i].strip()
                if not text.isdigit() and "<" not in text and text not in seen_texts:
                    text_lines.append(text)
                    seen_texts.add(text)
                i += 1
            if text_lines:
                transcript.append({"start": start_seconds, "text": " ".join(text_lines)})
        else:
            i += 1
    return transcript


def format_transcript(transcript):
    """Format transcript as timestamped plain text."""
    lines = []
    for entry in transcript:
        start = int(entry["start"])
        mins, secs = divmod(start, 60)
        lines.append(f"[{mins:02d}:{secs:02d}] {entry['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ingest-integrity gate (topic-agnostic). Seed of a general video-ingest skill.
# Surfaces completeness + announced-count facts so a truncated or under-counted
# pull can never *look* finished. Makes NO assumption that a video is about OSS.
# ---------------------------------------------------------------------------
_ENUM_NOUNS = (
    "projects|repos|repositories|tools|apps|tips|ways|things|models|papers|"
    "reasons|steps|libraries|frameworks|features|updates|alternatives|prompts|"
    "commands|extensions|plugins|hacks|tricks|ideas|examples|mistakes|lessons|"
    "questions|techniques|apps|gadgets|builds|demos"
)
_STOPWORD_END = {
    "a", "an", "the", "and", "or", "to", "of", "with", "for", "in", "on",
    "is", "its", "it's", "that", "this", "as", "at", "by", "but", "so",
}


def integrity_gate(transcript, video_title=None):
    """Topic-agnostic transcript-integrity report, returned as a banner string.

    Two checks, both true for ANY subject (3D, research, review, OSS, ...):
      - completeness: does the transcript end on a complete sentence, or is it
        cut mid-thought (no terminal punctuation / ends on a stopword)?
      - enumeration:  does the title/intro announce a count ("35 projects",
        "20 tips", "10 papers")? If so, surface it so the count can be
        reconciled downstream. No number -> freeform, no count gate.
    Returns "" for an empty transcript.
    """
    if not transcript:
        return ""
    raw = (transcript[-1].get("text") or "").strip()
    # strip trailing caption decoration (music notes, applause marks, dashes)
    last = re.sub(r"[\s♪♫♬🎵🎶\*_~\-]+$", "", raw)
    tokens = last.split()
    complete = last.endswith((".", "!", "?", '"', "”", "’", ")", "]", "…"))
    last_word = tokens[-1].lower().strip(".,;:!?…\"')]").replace("’", "'") if tokens else ""
    ends_stopword = (not tokens) or last_word in _STOPWORD_END
    truncated = (not complete) or ends_stopword

    hay = ((video_title or "") + " " + " ".join(e.get("text", "") for e in transcript[:12])).lower()
    hay = re.sub(r"#\s*\d+", " ", hay)  # drop episode/issue markers ("HN #10") so they can't pose as the count
    # number must be adjacent to the noun, with only alphabetic adjectives ("self-hosted") allowed between
    m = re.search(r"\b(\d{1,3})\s+(?:[a-z][a-z-]*\s+){0,2}?(" + _ENUM_NOUNS + r")\b", hay)
    announced = (int(m.group(1)), m.group(2)) if m else None

    last_stamp = int(transcript[-1].get("start", 0))
    mm, ss = divmod(last_stamp, 60)

    lines = ["⚠ CINOPSIS INGEST-GATE"]
    if truncated:
        tail = last[-40:] if last else "(empty)"
        lines.append(f"completeness : ⚠ ends mid-sentence (…{tail}) — transcript likely TRUNCATED; final item incomplete")
    else:
        lines.append("completeness : OK — ends on a complete sentence")
    if announced:
        n, noun = announced
        lines.append(f"enumeration  : video announces {n} {noun} — confirm all {n} captured before calling ingest complete")
    else:
        lines.append("enumeration  : no announced count (freeform video — no count gate)")
    lines.append(f"coverage     : {len(transcript)} entries · last stamp {mm:02d}:{ss:02d}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube video transcripts")
    parser.add_argument("--video-id", required=True, help="YouTube video ID")
    parser.add_argument("--output", help="Custom output file path")
    args = parser.parse_args()

    print(f"Fetching transcript: {args.video_id}", flush=True)
    transcript, lang = get_transcript_ytdlp(args.video_id)

    if not transcript:
        print("Failed to fetch transcript (video may require login or have no subtitles)")
        return

    formatted = format_transcript(transcript)
    print(f"Transcript language: {lang}, {len(transcript)} entries")

    output_file = Path(args.output) if args.output else DATA_DIR / f"transcript_{args.video_id}.txt"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(formatted, encoding="utf-8")
    print(f"Saved to: {output_file}")

    json_file = DATA_DIR / f"transcript_{args.video_id}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
