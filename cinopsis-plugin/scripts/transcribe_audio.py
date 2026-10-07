#!/usr/bin/env python3
"""transcribe_audio.py - Agent-Reach's audio transcription, as a Cinopsis CLI.

Transcribes a URL (yt-dlp audio-only download) or a local audio/video file with
Groq or OpenAI Whisper through reach.transcribe (lifted raw from Agent-Reach).
Keys: groq_api_key / openai_api_key in data/reach/.agent-reach/config.yaml (reach_home()), or
GROQ_API_KEY / OPENAI_API_KEY. The local-pipeline transcript source uses the same
engine as its `reach-audio` ASR backend.

    python scripts/transcribe_audio.py <url-or-file> [--provider auto|groq|openai] [--output out.txt]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# >>> LIFT agent-reach@a19a171f agent_reach/cli.py:1588-1613
def _cmd_transcribe(args):
    """Transcribe a URL or local audio file via an explicitly selected provider."""
    from pathlib import Path

    from reach.transcribe import TranscribeError, transcribe  # seam: package import
    from reach.text import scrub_url_credentials  # seam: package import

    try:
        text = transcribe(
            args.source,
            provider=args.provider,
            allow_provider_fallback=getattr(
                args,
                "allow_provider_fallback",
                False,
            ),
        )
    except TranscribeError as e:
        print(f"❌ {scrub_url_credentials(e)}")
        sys.exit(1)

    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"✅ Transcript written to {args.output}")
    else:
        print(text)
# <<< LIFT


def main() -> int:
    from media.runtime import configure_stdio
    configure_stdio()
    ap = argparse.ArgumentParser(description="Transcribe a URL or local media file (Agent-Reach engine)")
    ap.add_argument("source", help="URL or local audio/video path")
    ap.add_argument("--provider", default="auto", choices=["auto", "groq", "openai"])
    ap.add_argument("--allow-provider-fallback", action="store_true",
                    help="auto mode only: send failed chunks to the next configured provider")
    ap.add_argument("--output", default=None, help="Write the transcript here instead of stdout")
    _cmd_transcribe(ap.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
