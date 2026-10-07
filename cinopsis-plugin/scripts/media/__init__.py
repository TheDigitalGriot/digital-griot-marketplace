"""Cinopsis media engine.

The modules in this package are a raw lift of claude-video's Watch skill
(https://github.com/bradautomates/claude-video at 03ceb42): gemini (Google watches
a URL), download (yt-dlp info-json + one caption track), transcribe (VTT parser,
segment normaliser), whisper (Groq/OpenAI remote ASR), local_whisperx, frames
(keyframe / scene / uniform extraction), watch_setup (dependency status) and watch
(the full verb). Each file fences the upstream code with LIFT markers; every line
that differs from upstream ends in a '# seam:' comment. scripts/verify_lift.py
proves both against the pinned sha.

Cinopsis reaches these through scripts/sources (transcript sources),
scripts/capture_frames.py (keyframes) and scripts/watch_video.py (the verb).
"""
