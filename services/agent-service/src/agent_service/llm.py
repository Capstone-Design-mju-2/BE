from typing import Any

import httpx


class LlmError(Exception):
    """The LLM API failed or answered in a shape the agent cannot use."""


class Llm:
    """OpenAI-compatible chat completions over httpx (ADR-92), with no retries: a failure falls back to the 1B rules."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._timeout = timeout

    async def complete(self, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return the assistant message and the token usage."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, headers=self._headers,
                                             json={"model": self._model, "messages": messages, "tools": tools})
                response.raise_for_status()
                body = response.json()
            return body["choices"][0]["message"], body.get("usage") or {}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise LlmError(f"{self._model} call failed: {error!r}") from error
