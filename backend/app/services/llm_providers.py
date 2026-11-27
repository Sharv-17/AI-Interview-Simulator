"""LLM provider abstraction for AI answer evaluation (Phase 2).

An LLMProvider takes a StructuredRequest (prompts + a JSON schema) and returns a
parsed JSON object. It knows nothing about interviews, rubrics or scores: that is
rubric_evaluator.py. Switching provider means changing LLM_PROVIDER, not the
evaluation logic.

Providers:
* anthropic           -- Messages API; the JSON is forced through a tool call
                         (tool_choice), so the model returns structured arguments
                         rather than prose to be scraped.
* openai_compatible   -- Chat Completions style API (OpenAI and compatible
                         servers) using JSON mode; the reply is parsed with
                         json.loads, never with regular expressions.
* mock                -- deterministic, TESTS ONLY (see mock_provider.py); refused
                         unless ALLOW_MOCK_LLM=true.

Safety:
* API keys are read from the environment only and are never logged or put in an
  error message.
* Error messages are fixed strings: the provider's response body is never copied
  into an exception (it can echo prompts or internal detail).
* Every call has a timeout. Retries live in the evaluator, driven by `retryable`.

NOTE: live calls to the real APIs have not been exercised in this repository's
tests (no key was available). The request/response shapes are covered with
mocked HTTP only; verify against the live API before relying on them.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

import httpx

from app import config

logger = logging.getLogger(__name__)


# --- Errors -------------------------------------------------------------------


class LLMProviderError(Exception):
    """Base class. `code` is stable; `retryable` says whether trying again can help."""

    code = "llm_error"
    retryable = False
    message = "The language model request failed."

    def __init__(self, message: str = "", retry_after: Optional[float] = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.retry_after = retry_after


class LLMNotConfiguredError(LLMProviderError):
    code = "llm_not_configured"
    message = "No language model is configured for answer evaluation."


class LLMAuthError(LLMProviderError):
    code = "llm_auth_failed"
    message = "The language model rejected the configured credentials."


class LLMRequestRejectedError(LLMProviderError):
    code = "llm_request_rejected"
    message = "The language model rejected the request."


class LLMTimeoutError(LLMProviderError):
    code = "llm_timeout"
    retryable = True
    message = "The language model did not respond in time."


class LLMRateLimitedError(LLMProviderError):
    code = "llm_rate_limited"
    retryable = True
    message = "The language model is rate limiting requests."


class LLMServerError(LLMProviderError):
    code = "llm_unavailable"
    retryable = True
    message = "The language model service is unavailable."


class LLMBadResponseError(LLMProviderError):
    code = "llm_invalid_response"
    retryable = True
    message = "The language model returned an unusable response."


# --- Request / provider interface ---------------------------------------------


@dataclass(frozen=True)
class StructuredRequest:
    """One structured-output call. `metadata` is NEVER sent to a provider; it exists
    so test doubles can behave deterministically without parsing prompts."""

    system: str
    user: str
    schema: Dict[str, Any]
    schema_name: str = "submit_evaluation"
    schema_description: str = "Submit the structured evaluation of the candidate's answer."
    metadata: Mapping[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    name: str = "llm"

    @abstractmethod
    def complete_json(self, request: StructuredRequest) -> Dict[str, Any]:
        """Return the model's structured output as a dict, or raise LLMProviderError."""
        raise NotImplementedError


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _post_json(
    client: httpx.Client, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float
) -> Dict[str, Any]:
    """POST and classify the outcome into typed errors. Never leaks bodies or headers."""
    try:
        response = client.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.TimeoutException:
        raise LLMTimeoutError() from None
    except httpx.HTTPError:
        raise LLMServerError("Could not reach the language model service.") from None

    status = response.status_code
    if status in (401, 403):
        raise LLMAuthError()
    if status == 429:
        raise LLMRateLimitedError(retry_after=_retry_after_seconds(response))
    if status >= 500:
        raise LLMServerError(retry_after=_retry_after_seconds(response))
    if status >= 400:
        logger.warning("LLM request rejected with HTTP %s", status)
        raise LLMRequestRejectedError()
    try:
        data = response.json()
    except ValueError:
        raise LLMBadResponseError() from None
    if not isinstance(data, dict):
        raise LLMBadResponseError()
    return data


# --- Anthropic ------------------------------------------------------------------


class AnthropicProvider(LLMProvider):
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 30.0,
        max_tokens: int = 1500,
        temperature: Optional[float] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key:
            raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set.")
        self._api_key = api_key
        self.model = model
        self._url = base_url.rstrip("/") + "/v1/messages"
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = client or httpx.Client()
        self.name = f"anthropic:{model}"

    def complete_json(self, request: StructuredRequest) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "tools": [
                {
                    "name": request.schema_name,
                    "description": request.schema_description,
                    "input_schema": request.schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": request.schema_name},
        }
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        data = _post_json(self._client, self._url, headers, payload, self._timeout)

        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise LLMBadResponseError()
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == request.schema_name:
                arguments = block.get("input")
                if isinstance(arguments, dict):
                    return arguments
        raise LLMBadResponseError()


# --- OpenAI-compatible ----------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key:
            raise LLMNotConfiguredError("OPENAI_API_KEY is not set.")
        if not model:
            raise LLMNotConfiguredError("OPENAI_MODEL is not set.")
        self._api_key = api_key
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._timeout = timeout
        self._client = client or httpx.Client()
        self.name = f"openai_compatible:{model}"

    def complete_json(self, request: StructuredRequest) -> Dict[str, Any]:
        schema_hint = (
            "Respond with ONE JSON object only, matching exactly this JSON schema "
            f"(no prose, no code fences):\n{_compact_json(request.schema)}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system + "\n\n" + schema_hint},
                {"role": "user", "content": request.user},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"authorization": f"Bearer {self._api_key}", "content-type": "application/json"}
        data = _post_json(self._client, self._url, headers, payload, self._timeout)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMBadResponseError() from None
        if not isinstance(content, str):
            raise LLMBadResponseError()
        import json

        try:
            parsed = json.loads(content)
        except ValueError:
            raise LLMBadResponseError() from None
        if not isinstance(parsed, dict):
            raise LLMBadResponseError()
        return parsed


def _compact_json(value: Any) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


# --- Factory --------------------------------------------------------------------

_provider_cache: Dict[Tuple, LLMProvider] = {}


def get_llm_provider() -> LLMProvider:
    """Build the configured provider from the environment-backed settings.

    Raises LLMNotConfiguredError if nothing usable is configured. There is no
    silent fallback to a fake provider.
    """
    name = config.LLM_PROVIDER
    if not name:
        raise LLMNotConfiguredError("LLM_PROVIDER is not set.")

    if name == "mock":
        if not config.ALLOW_MOCK_LLM:
            raise LLMNotConfiguredError("The mock provider is for automated tests only (ALLOW_MOCK_LLM is not true).")
        from app.services.mock_provider import MockProvider

        return MockProvider()

    if name == "anthropic":
        key = (name, config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL, config.ANTHROPIC_BASE_URL)
        if key not in _provider_cache:
            _provider_cache[key] = AnthropicProvider(
                api_key=config.ANTHROPIC_API_KEY,
                model=config.ANTHROPIC_MODEL,
                base_url=config.ANTHROPIC_BASE_URL,
                timeout=config.LLM_TIMEOUT_SECONDS,
                max_tokens=config.LLM_MAX_TOKENS,
            )
        return _provider_cache[key]

    if name == "openai_compatible":
        key = (name, config.OPENAI_API_KEY, config.OPENAI_MODEL, config.OPENAI_BASE_URL)
        if key not in _provider_cache:
            _provider_cache[key] = OpenAICompatibleProvider(
                api_key=config.OPENAI_API_KEY,
                model=config.OPENAI_MODEL,
                base_url=config.OPENAI_BASE_URL,
                timeout=config.LLM_TIMEOUT_SECONDS,
            )
        return _provider_cache[key]

    raise LLMNotConfiguredError(f"Unknown LLM_PROVIDER {name!r}. Use 'anthropic' or 'openai_compatible'.")
