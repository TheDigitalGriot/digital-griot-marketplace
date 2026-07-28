#!/usr/bin/env python3
"""Provider: Claude via the Anthropic API key (fallback for machines without the CLI)."""


class ClaudeKeyProvider:
    name = "claude_key"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key
        self.model = model or "claude-sonnet-4-6"

    def stream(self, context: str, question: str):
        import anthropic

        if not self.api_key:
            raise RuntimeError("No Anthropic API key configured (set one in Settings or ANTHROPIC_API_KEY).")
        client = anthropic.Anthropic(api_key=self.api_key)
        with client.messages.stream(
            model=self.model,
            max_tokens=2048,
            system=context,
            messages=[{"role": "user", "content": question}],
        ) as stream:
            for text in stream.text_stream:
                yield text
