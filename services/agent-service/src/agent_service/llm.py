import asyncio
from typing import Any

import httpx


class LlmError(Exception):
    """The LLM API failed or answered in a shape the agent cannot use."""

    def __init__(self, message: str, provider_down: bool = False) -> None:
        super().__init__(message)
        # Slow, rate limited or failing on the provider's side, unlike an answer the agent cannot use. Only these move
        # the chat to the fallback LLM (ADR-129).
        self.provider_down = provider_down


class Llm:
    """OpenAI-compatible chat completions over httpx (ADR-92), with no retries: a failure falls back to the 1B rules."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float,
                 call_timeout: float | None = None) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.model = model
        self.timeout = timeout
        # A cap on one call, set when a fallback LLM waits so that it still gets time (ADR-129).
        self.call_timeout = call_timeout

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                       timeout: float | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return the assistant message and the token usage. timeout is what is left of the chat's limit."""
        limit = self.timeout if timeout is None else timeout
        if self.call_timeout is not None:
            limit = min(limit, self.call_timeout)
        try:
            if limit <= 0:
                raise TimeoutError("no time left for another call")
            # httpx timeouts apply per read, so a server that keeps trickling bytes would never time out on its own.
            async with asyncio.timeout(limit), httpx.AsyncClient(timeout=limit) as client:
                response = await client.post(self._url, headers=self._headers,
                                             json={"model": self.model, "messages": messages, "tools": tools})
                response.raise_for_status()
                body = response.json()
            return body["choices"][0]["message"], body.get("usage") or {}
        except (TimeoutError, httpx.TransportError) as error:
            raise LlmError(f"{self.model} call failed: {error!r}", provider_down=True) from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise LlmError(f"{self.model} call failed: {error!r}",
                           provider_down=status == 429 or status >= 500) from error
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise LlmError(f"{self.model} call failed: {error!r}") from error
