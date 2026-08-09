#!/usr/bin/env python3
"""Fetch video transcripts via an environment-aware fallback ladder.

Ladder (cloud <-> local aware; each rung degrades to the next):
  0. cache   - reuse data/transcript_<id>.json if present (idempotent)
  1. api     - youtube-transcript-api, instance .fetch() (shim for old .get_transcript);
               fastest, no yt-dlp needed, but requires YouTube egress
  2. yt-dlp  - subtitle download with cookie fallbacks (works where the API is proxy-blocked)
  3. asr     - OPTIONAL last rung for caption-LESS videos: yt-dlp audio -> faster-whisper
               (only fires if faster-whisper is importable; else logs a one-line enable hint)
If every rung fails, the caller is told to use the Chrome caption-scrape rung
(agent-side: read ytInitialPlayerResponse.captionTracks off the loaded watch page).

Why this exists: the working method kept getting re-derived every session. It is
now baked into the tool + pinned in SKILL.md and /topics/cinopsis-method.
"""
import json
import os
import sys
import argparse
import re
import subprocess
from pathlib import Path

from _utils import find_ytdlp, get_env, DATA_DIR


def _find_ytdlp():
    return find_ytdlp()


# ---------------------------------------------------------------------------
# Rung 0 - cache
# ---------------------------------------------------------------------------
def load_cached_transcript(video_id):
    """Return (transcript, 'cache') if a cached JSON exists, else (None, None)."""
    jf = DATA_DIR / f"transcript_{video_id}.json"
    if jf.exists():
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            if data:
                return data, "cache"
        except Exception:
            pass
    return None, None


# ---------------------------------------------------------------------------
# Rung 1 - youtube-transcript-api (preferred; needs egress)
# ---------------------------------------------------------------------------
def get_transcript_api(video_id, languages=("en", "en-US", "en-GB", "zh", "zh-Hans")):
    """Fetch via youtube-transcript-api. Uses the modern instance API
    ``YouTubeTranscriptApi().fetch(id)`` and shims the legacy static
    ``.get_transcript(id)``. Returns (transcript, lang) or (None, None)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("  [api] youtube-transcript-api not installed; skipping API rung", flush=True)
        return None, None

    langs = list(languages)
    raw = None
    # Modern instance API (0.6.2+/1.x)
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=langs)
        if hasattr(fetched, "to_raw_data"):
            raw = fetched.to_raw_data()
        else:
            raw = [{"text": getattr(s, "text", ""), "start": getattr(s, "start", 0),
                    "duration": getattr(s, "duration", 0)} for s in fetched]
    except AttributeError:
        # Legacy static API shim (<=0.6.1)
        try:
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
        except Exception as e:
            print(f"  [api] legacy get_transcript shim failed: {type(e).__name__}: {e}", flush=True)
            return None, None
    except Exception as e:
        # ProxyError / RequestBlocked / TranscriptsDisabled / no-egress all land here
        print(f"  [api] fetch failed ({type(e).__name__}): {e}", flush=True)
        return None, None

    if not raw:
        return None, None
    transcript = [
        {"start": float(r.get("start", 0) or 0), "text": (r.get("text") or "").replace("\n", " ").strip()}
        for r in raw if (r.get("text") or "").strip()
    ]
    return (transcript, "en") if transcript else (None, None)


# ---------------------------------------------------------------------------
# Rung 2 - yt-dlp subtitle download (works where the API is proxy-blocked)
# ---------------------------------------------------------------------------
def get_transcript_ytdlp(video_id):
    """Fetch subtitles using yt-dlp with a 3-tier cookie fallback:
      1. no cookies (most public videos)  2. Chrome cookies  3. Firefox cookies
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = str(DATA_DIR / f"sub_{video_id}")

    ytdlp = _find_ytdlp()
    if not ytdlp:
        print("  [yt-dlp] binary not found on PATH/venv; skipping yt-dlp rung", flush=True)
        return None, None
    base_cmd = [
        ytdlp, "--skip-download",
        "--write-auto-sub", "--write-sub",
        "--sub-lang", "en,zh",
        "--sub-format", "vtt",
        "-o", output_template,
    ]

    print("  [yt-dlp] fetching subtitles without cookies...", flush=True)
    subprocess.run(base_cmd + [url], capture_output=True, env=get_env(), timeout=60, stdin=subprocess.DEVNULL)

    result = _find_vtt(video_id)
    if result[0]:
        return result

    print("  [yt-dlp] retrying with Chrome cookies...", flush=True)
    subprocess.run(base_cmd + ["--cookies-from-browser", "chrome", url],
                   capture_output=True, env=get_env(), timeout=60, stdin=subprocess.DEVNULL)
    result = _find_vtt(video_id)
    if result[0]:
        return result

    print("  [yt-dlp] retrying with Firefox cookies...", flush=True)
    subprocess.run(base_cmd + ["--cookies-from-browser", "firefox", url],
                   capture_output=True, env=get_env(), timeout=60, stdin=subprocess.DEVNULL)
    return _find_vtt(video_id)


def _find_vtt(video_id):
    """Find generated subtitle files in the data directory."""
    for suffix in [".en.vtt", ".zh.vtt", ".en-orig.vtt", ".zh-Hans.vtt"]:
        sub_file = DATA_DIR / f"sub_{video_id}{suffix}"
        if sub_file.exists():
            lang = suffix.split(".")[1]
            return parse_vtt(sub_file), lang
    return None, None


# ---------------------------------------------------------------------------
# Rung 3 - OPTIONAL ASR (caption-less videos): yt-dlp audio -> faster-whisper
# ---------------------------------------------------------------------------
def get_transcript_asr(video_id):
    """Last resort for videos with NO captions at all. Downloads audio with
    yt-dlp and transcribes locally with faster-whisper. Optional hook: fires
    only if faster-whisper is installed (CTranslate2 backend - avoids the
    torch/CUDA-wheel dance). Set CINOPSIS_WHISPER_MODEL to pick a size."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  [asr] faster-whisper not installed; skipping ASR rung "
              "(enable with: pip install faster-whisper)", flush=True)
        return None, None

    ytdlp = _find_ytdlp()
    if not ytdlp:
        print("  [asr] yt-dlp not found; cannot fetch audio for ASR", flush=True)
        return None, None

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "audio.%(ext)s")
        cmd = [ytdlp, "-x", "--audio-format", "mp3", "--audio-quality", "5",
               "-o", out, f"https://www.youtube.com/watch?v={video_id}"]
        print("  [asr] downloading audio for local transcription...", flush=True)
        subprocess.run(cmd, capture_output=True, env=get_env(), timeout=300, stdin=subprocess.DEVNULL)
        audio = next((str(f) for f in Path(td).glob("audio.*")), None)
        if not audio:
            print("  [asr] audio download failed", flush=True)
            return None, None
        model_size = os.environ.get("CINOPSIS_WHISPER_MODEL", "base")
        print(f"  [asr] transcribing with faster-whisper ({model_size})...", flush=True)
        model = WhisperModel(model_size, device="auto", compute_type="int8")
        segments, info = model.transcribe(audio)
        transcript = [{"start": float(seg.start), "text": seg.text.strip()}
                      for seg in segments if seg.text and seg.text.strip()]
    lang = getattr(info, "language", "asr") if transcript else None
    return (transcript, lang) if transcript else (None, None)


# ---------------------------------------------------------------------------
# The ladder dispatcher
# ---------------------------------------------------------------------------
def fetch_transcript(video_id, allow_cache=True, refresh=False):
    """Run the fallback ladder. Returns (transcript, lang, method)."""
    if allow_cache and not refresh:
        cached, _ = load_cached_transcript(video_id)
        if cached:
            print(f"  [cache] using cached transcript ({len(cached)} entries)", flush=True)
            return cached, "cache", "cache"

    for name, fn in (("api", get_transcript_api),
                     ("yt-dlp", get_transcript_ytdlp),
                     ("asr", get_transcript_asr)):
        try:
            print(f"  [ladder] trying rung: {name}", flush=True)
            t, lang = fn(video_id)
            if t:
                print(f"  [ladder] {name} succeeded ({len(t)} entries)", flush=True)
                return t, lang, name
        except Exception as e:
            print(f"  [ladder] {name} error: {type(e).__name__}: {e}", flush=True)

    print("  [ladder] all rungs failed. Rung 4 (agent-side): use the Chrome "
          "caption-scrape - load the watch page and read "
          "ytInitialPlayerResponse.captions.playerCaptionsTracklistRenderer.captionTracks.", flush=True)
    return None, None, None


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


def save_transcript(video_id, transcript, output=None):
    """Persist the transcript as both .txt (timestamped) and .json (cache)."""
    formatted = format_transcript(transcript)
    out = Path(output) if output else DATA_DIR / f"transcript_{video_id}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(formatted, encoding="utf-8")
    (DATA_DIR / f"transcript_{video_id}.json").write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


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
    """Topic-agnostic transcript-integrity report, returned as a banner string."""
    if not transcript:
        return ""
    raw = (transcript[-1].get("text") or "").strip()
    last = re.sub(r"[\s♪♫♬\U0001F3B5\U0001F3B6\*_~\-]+$", "", raw)
    tokens = last.split()
    complete = last.endswith((".", "!", "?", '"', "”", "’", ")", "]", "…"))
    last_word = tokens[-1].lower().strip(".,;:!?…\"')]").replace("’", "'") if tokens else ""
    ends_stopword = (not tokens) or last_word in _STOPWORD_END
    truncated = (not complete) or ends_stopword

    hay = ((video_title or "") + " " + " ".join(e.get("text", "") for e in transcript[:12])).lower()
    hay = re.sub(r"#\s*\d+", " ", hay)
    m = re.search(r"\b(\d{1,3})\s+(?:[a-z][a-z-]*\s+){0,2}?(" + _ENUM_NOUNS + r")\b", hay)
    announced = (int(m.group(1)), m.group(2)) if m else None

    last_stamp = int(transcript[-1].get("start", 0))
    mm, ss = divmod(last_stamp, 60)

    lines = ["⚠ CINOPSIS INGEST-GATE"]
    if truncated:
        tail = last[-40:] if last else "(empty)"
        lines.append(f"completeness : ⚠ ends mid-sentence (...{tail}) - transcript likely TRUNCATED; final item incomplete")
    else:
        lines.append("completeness : OK - ends on a complete sentence")
    if announced:
        n, noun = announced
        lines.append(f"enumeration  : video announces {n} {noun} - confirm all {n} captured before calling ingest complete")
    else:
        lines.append("enumeration  : no announced count (freeform video - no count gate)")
    lines.append(f"coverage     : {len(transcript)} entries · last stamp {mm:02d}:{ss:02d}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube video transcripts (fallback ladder)")
    parser.add_argument("--video-id", required=True, help="YouTube video ID")
    parser.add_argument("--output", help="Custom output file path")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache and re-fetch")
    parser.add_argument("--no-cache", action="store_true", help="Do not read the on-disk cache")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print(f"Fetching transcript: {args.video_id}", flush=True)
    transcript, lang, method = fetch_transcript(
        args.video_id, allow_cache=not args.no_cache, refresh=args.refresh)

    if not transcript:
        print("Failed to fetch transcript via every rung (api / yt-dlp / asr). "
              "If you have a browser agent, use the Chrome caption-scrape rung.")
        raise SystemExit(1)

    output_file = save_transcript(args.video_id, transcript, args.output)
    print(f"Transcript: {lang}, {len(transcript)} entries (via {method})")
    print(f"Saved to: {output_file}")
    print(integrity_gate(transcript))


if __name__ == "__main__":
    main()
