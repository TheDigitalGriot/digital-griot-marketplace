"""local-pipeline - yt-dlp info-json + one caption track, ASR when there is none.

Built from claude-video's local engine (scripts/media, lifted raw):

  1. ONE yt-dlp --write-info-json call (media.download.fetch_captions) gives
     title, description, chapters and the caption inventory. Cinopsis writes
     data/description_<id>.txt and data/links_<id>.json from it (R4 - before v3
     nothing wrote those files).
  2. media.download.select_caption picks one track (manual over automatic,
     original language over translations) and a second yt-dlp call reuses the
     info JSON to fetch only that track; media.transcribe.parse_vtt reads it.
  3. No caption track -> the ASR backends, in Agent-Reach's ordered-backend
     order (override with env LOCAL_PIPELINE_BACKEND or settings
     local-pipeline_backend):
       whisper-remote  media.whisper.transcribe_video (Groq / OpenAI)
       reach-audio     reach.transcribe.transcribe (Agent-Reach audio-only path)
       whisperx        media.local_whisperx (local model)

The rung sits on the timedtext door; a 429 from yt-dlp cools that door only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

from sources import SourceError, TranscriptSource

LINK_HOSTS = {"github": ("github.com",), "gitlab": ("gitlab.com",),
              "huggingface": ("huggingface.co", "hf.co")}
_URL = re.compile(r"https?://[^\s<>\"')\]]+")


def _data_dir() -> Path:
    from _utils import DATA_DIR
    return Path(DATA_DIR)


def _settings() -> dict:
    try:
        from app_settings import load_settings
        return load_settings()
    except Exception:
        return {}


class _BackendConfig:
    """Channel.ordered_backends() config: settings key, then env with dashes as underscores."""

    def __init__(self, settings: dict):
        self.settings = settings

    def get(self, key, default=None):
        return (self.settings.get(key) or os.environ.get(key.upper().replace("-", "_")) or default)


# ---- R4: the description writer -------------------------------------------------

def extract_links(text: str) -> dict:
    from reach.url import host_matches
    out = {k: [] for k in LINK_HOSTS}
    for raw in _URL.findall(text or ""):
        url = raw.rstrip(".,;:!?")
        for kind, hosts in LINK_HOSTS.items():
            if host_matches(url, *hosts) and url not in out[kind]:
                out[kind].append(url)
    return out


def write_description(video_id: str, info: dict, data_dir: Optional[Path] = None) -> dict:
    """Write description_<id>.txt and links_<id>.json from a yt-dlp info dict."""
    data_dir = Path(data_dir or _data_dir())
    data_dir.mkdir(parents=True, exist_ok=True)
    desc = info.get("description") or ""
    d_path = data_dir / f"description_{video_id}.txt"
    d_path.write_text(desc, encoding="utf-8", newline="\n")
    links = extract_links(desc)
    l_path = data_dir / f"links_{video_id}.json"
    l_path.write_text(json.dumps({"video_id": video_id, "title": info.get("title"),
                                  "channel": info.get("channel") or info.get("uploader"),
                                  "links": links}, indent=2, ensure_ascii=False),
                      encoding="utf-8", newline="\n")
    return {"description": str(d_path), "links": str(l_path),
            "chars": len(desc), "link_counts": {k: len(v) for k, v in links.items()}}


def fetch_info(url: str, out_dir: Path, *, cookies_file=None, cookies_from_browser=None) -> tuple[dict, Path]:
    """The single info-json yt-dlp call (no captions, no media). Returns (info, run_dir)."""
    from media import download
    auth = download.auth_args(cookies_file, cookies_from_browser)
    run = download._new_run(out_dir)
    download._run([*download._common(run, auth), "--skip-download", "--write-info-json",
                   "--no-write-subs", "--no-write-auto-subs", "--", url])
    return download._read_metadata(run / "video.info.json"), run


def _watch_auth() -> dict:
    from media import config as watch_config
    try:
        cfg = watch_config.get_config()
    except watch_config.ConfigError:
        return {}
    return {"cookies_file": cfg.get("cookies_file") or None,
            "cookies_from_browser": cfg.get("cookies_from_browser") or None}


def _to_cinopsis(segments) -> list[dict]:
    return [{"start": int(s["start"]), "text": s["text"]} for s in segments if str(s.get("text", "")).strip()]


# ---- ASR backends ----------------------------------------------------------------

def _asr_whisper_remote(url, run_root, context):
    from media import config as watch_config, download, whisper
    backend, key = watch_config.load_api_key()
    if not key:
        return None, "whisper-remote: no GROQ_API_KEY / OPENAI_API_KEY"
    media = download.download_url(url, run_root, audio_only=True, context=context, **_watch_auth())
    segs, used = whisper.transcribe_video(media["video_path"], Path(media["run_dir"]) / "audio.mp3",
                                          backend=backend, api_key=key)
    return _to_cinopsis(segs), f"whisper-remote ({used})"


def _asr_reach_audio(url, run_root, context):
    from reach.config import Config
    from reach import transcribe as reach_transcribe
    cfg = Config(read_only=True)
    if not (cfg.is_configured("groq_whisper") or cfg.is_configured("openai_whisper")):
        return None, "reach-audio: no groq_api_key / openai_api_key in Agent-Reach config or env"
    text = reach_transcribe.transcribe(url, provider="auto", config=cfg)
    # Agent-Reach returns joined text without cue times; keep it as one untimed block.
    return ([{"start": 0, "text": text.strip()}] if text.strip() else None), "reach-audio (untimed)"


def _asr_whisperx(url, run_root, context):
    from media import download, local_whisperx, whisper
    try:
        local_whisperx.executable_path()
    except SystemExit as exc:
        return None, f"whisperx: {exc}"
    media = download.download_url(url, run_root, audio_only=True, context=context, **_watch_auth())
    segs, _ = whisper.transcribe_video(media["video_path"], Path(media["run_dir"]) / "audio.mp3",
                                       backend="whisperx")
    return _to_cinopsis(segs), "whisperx"


ASR = {"whisper-remote": _asr_whisper_remote, "reach-audio": _asr_reach_audio, "whisperx": _asr_whisperx}


def fetch_local_pipeline(video_id: str):
    """Rung: captions via info-json + one track; ASR fallback. (segments, lang) or (None, None)."""
    from media import download, transcribe
    settings = _settings()
    url = f"https://www.youtube.com/watch?v={video_id}"
    run_root = _data_dir() / "media_runs"
    result = download.fetch_captions(url, run_root, sub_lang=settings.get("sub_lang") or "auto", **_watch_auth())
    run_dir = Path(result["run_dir"])
    notes = list(result.get("errors") or [])
    try:
        if result.get("info_path"):
            info = json.loads(Path(result["info_path"]).read_text(encoding="utf-8"))
            write_description(video_id, info)
        if result.get("subtitle_path"):
            segs = _to_cinopsis(transcribe.parse_vtt(result["subtitle_path"]))
            track = result.get("caption_track") or {}
            if segs:
                return segs, track.get("language") or "auto"
        if notes and not result.get("info_path"):
            # yt-dlp could not even read the page: report it so the door records it.
            raise SourceError("; ".join(notes))
        source = LocalPipelineSource()
        for backend in source.ordered_backends(_BackendConfig(settings)):
            fn = ASR.get(backend)
            if fn is None:
                continue
            try:
                segs, note = fn(url, run_root, result)
            except SystemExit as exc:
                segs, note = None, f"{backend}: {exc}"
            notes.append(note)
            if segs:
                print(f"[local-pipeline] {note}", file=sys.stderr)
                return segs, "auto"
        print("[local-pipeline] no caption track and no ASR backend produced text: " + " | ".join(notes),
              file=sys.stderr)
        return None, None
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


class LocalPipelineSource(TranscriptSource):
    name = "local-pipeline"
    description = "yt-dlp info-json + caption track, ASR fallback (Watch local engine)"
    backends = ["captions", "whisper-remote", "reach-audio", "whisperx"]
    tier = 0
    kind = "caption"
    door = "timedtext"

    def rungs(self):
        return [("local-pipeline", fetch_local_pipeline, "timedtext")]

    def check(self, config=None):
        from _utils import find_ytdlp
        from reach.probe import probe_command
        from media import config as watch_config
        probe = probe_command(find_ytdlp(), ["--version"], timeout=10, package="yt-dlp")
        if not probe.ok:
            self.active_backend = None
            return ("off" if probe.status == "missing" else "error"), f"yt-dlp {probe.status}: {probe.hint or probe.output}"
        self.active_backend = "captions"
        asr = []
        if watch_config.load_api_key()[1]:
            asr.append("whisper-remote")
        try:
            from reach.config import Config
            cfg = Config(read_only=True)
            if cfg.is_configured("groq_whisper") or cfg.is_configured("openai_whisper"):
                asr.append("reach-audio")
        except Exception:
            pass
        missing = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
        msg = f"yt-dlp {probe.output.splitlines()[0] if probe.output else 'ok'}; captions ready"
        msg += f"; ASR: {', '.join(asr)}" if asr else "; no ASR key (caption-less videos will miss)"
        if missing and asr:
            return "warn", msg + f"; ASR needs {', '.join(missing)}"
        return "ok", msg
