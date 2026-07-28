#!/usr/bin/env python3
"""Provider: any OpenAI-compatible HTTP endpoint (your custom / fine-tuned local models).

Vendor-neutral — speaks the OpenAI-compatible ``/v1/chat/completions`` wire
protocol over plain HTTP. Point ``base_url`` at Ollama, llama.cpp, vLLM,
LM Studio, or your own server. NOT the `openai` package — just `requests`.
"""


class LocalEndpointProvider:
    name = "local"

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or "http://localhost:11434/v1").rstrip("/")
        self.model = model or ""
        self.api_key = api_key or ""

    def stream(self, context: str, question: str):
        import json
        import requests

        if not self.model:
            raise RuntimeError("No local model configured (set 'local_model' in Settings).")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": context},
                {"role": "user", "content": question},
            ],
            "stream": True,
        }
        with requests.post(f"{self.base_url}/chat/completions", json=payload,
                           headers=headers, stream=True, timeout=120) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[len("data:"):].strip()
                if line == "[DONE]":
                    break
                try:
                    obj = json.loads(line)
                    delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
                except Exception:
                    continue
