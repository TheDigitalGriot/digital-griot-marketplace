#!/usr/bin/env python3
"""Provider: Claude via the Agent SDK using the local `claude` CLI (Max/Pro subscription).

This is the primary path (mirrors the quiz-assistant pattern): no API key, no
per-token cost. Requires the `claude` CLI installed and `claude login`. The Agent
SDK is async; we bridge it to a synchronous chunk iterator for Flask.
"""
import asyncio
import queue
import threading


def _run_async_gen(agen_factory):
    """Drive an async generator from a worker thread, yielding items synchronously."""
    q = queue.Queue()
    sentinel = object()

    def run():
        async def pump():
            async for item in agen_factory():
                q.put(item)
        try:
            asyncio.run(pump())
        except Exception as e:  # surface to the consumer
            q.put(e)
        finally:
            q.put(sentinel)

    threading.Thread(target=run, daemon=True).start()
    while True:
        item = q.get()
        if item is sentinel:
            break
        if isinstance(item, Exception):
            raise item
        yield item


class ClaudeSubProvider:
    name = "claude_sub"

    def stream(self, context: str, question: str):
        from claude_agent_sdk import (
            query, ClaudeAgentOptions, AssistantMessage, TextBlock,
        )

        async def agen():
            options = ClaudeAgentOptions(
                system_prompt=context,
                permission_mode="default",
                allowed_tools=[],
                max_turns=2,
            )
            async for message in query(prompt=question, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            yield block.text

        yield from _run_async_gen(agen)
