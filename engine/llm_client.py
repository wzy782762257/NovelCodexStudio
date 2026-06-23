#!/usr/bin/env python3
"""OpenAI-compatible LLM API client with retry and timeout."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        timeout: int = 120,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        last_error = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    return str(result["choices"][0]["message"]["content"])
            except urllib.error.HTTPError as exc:
                last_error = exc
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429:
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                if exc.code >= 500:
                    time.sleep(1)
                    continue
                raise RuntimeError(f"LLM API HTTP {exc.code}: {body}") from exc
            except Exception as exc:
                last_error = exc
                time.sleep(1)
                continue

        raise RuntimeError(f"LLM API failed after {self.max_retries} retries: {last_error}")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Call with JSON response format and parse result."""
        content = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        # Some providers return markdown code fences; strip them.
        text = content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        return json.loads(text)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import EngineConfig

    cfg = EngineConfig.load(Path("config.json"))
    client = LLMClient(cfg.base_url, cfg.api_key, cfg.model)
    print(f"Testing LLM: model={cfg.model}, base_url={cfg.base_url}")
    try:
        resp = client.chat([{"role": "user", "content": "请只回复：API测试成功"}])
        print(f"Response: {resp}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
