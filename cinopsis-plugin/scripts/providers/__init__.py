#!/usr/bin/env python3
"""Pluggable chat-provider layer.

All providers expose ``stream(context, question) -> Iterator[str]`` (text chunks).
``chat_stream`` selects the active provider from settings and, per decision Q4->B,
falls back from the subscription CLI to the Anthropic API key when the `claude`
CLI is unavailable.
"""
import os

from .claude_sub import ClaudeSubProvider
from .claude_key import ClaudeKeyProvider
from .local_endpoint import LocalEndpointProvider

# CLI-absent / auth failure signatures that should trigger the key fallback.
_FALLBACK_SIGNS = ("spawn", "enoent", "auth", "not found", "credential", "cli", "filenotfound")


def get_provider(settings: dict):
    name = settings.get("provider", "claude_sub")
    if name == "claude_key":
        return ClaudeKeyProvider(
            api_key=settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY"),
            model=settings.get("model"),
        )
    if name == "local":
        return LocalEndpointProvider(
            base_url=settings.get("local_base_url"),
            model=settings.get("local_model"),
            api_key=settings.get("local_api_key"),
        )
    return ClaudeSubProvider()


def chat_stream(settings: dict, context: str, question: str):
    """Yield answer chunks, with subscription->API-key fallback before the first chunk."""
    name = settings.get("provider", "claude_sub")
    primary = get_provider(settings)
    try:
        gen = primary.stream(context, question)
        first = next(gen)
    except StopIteration:
        return
    except Exception as e:
        key = settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if name == "claude_sub" and key and any(s in str(e).lower() for s in _FALLBACK_SIGNS):
            try:
                yield from ClaudeKeyProvider(api_key=key, model=settings.get("model")).stream(context, question)
            except Exception as e2:
                yield f"[chat error] {e2}"
            return
        yield f"[chat error] {e}"
        return
    yield first
    try:
        yield from gen
    except Exception as e:
        yield f"\n[chat error] {e}"
