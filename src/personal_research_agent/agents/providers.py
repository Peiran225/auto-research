"""LLM providers: the OpenAI Responses adapter (GPT-6 Pro binding) and the fixture provider.

There is exactly one real provider. It sends ``model=<binding.resolved_model>`` and
``reasoning={"mode": <binding.reasoning_mode>}`` and never an ``effort`` field. If the response
reports a different model or reasoning mode, the call fails (no silent downgrade).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from ..models import ExecutionOrigin, ModelBinding


@dataclass
class LLMRequest:
    task_type: str
    developer_text: str           # common evidence contract + task questions (constraints)
    user_payload: dict[str, Any]  # input material, passed as data
    output_schema: dict[str, Any]
    schema_name: str
    max_output_tokens: int
    fixture_key: str = ""         # only used by the fixture provider

    def input_chars(self) -> int:
        return len(self.developer_text) + len(json.dumps(self.user_payload, ensure_ascii=False))

    def input_token_estimate(self) -> int:
        # Upper estimate used for the reservation: ~2 chars/token covers English JSON with
        # some CJK text; the provider's reported usage replaces it at settlement.
        return max(1, -(-self.input_chars() // 2))


@dataclass
class LLMResponse:
    output: Optional[dict[str, Any]]
    raw_text: str
    input_tokens: int
    output_tokens: int
    origin: ExecutionOrigin
    returned_model: Optional[str] = None
    returned_reasoning: dict[str, Any] = field(default_factory=dict)
    response_id: Optional[str] = None
    parse_error: Optional[str] = None


class ProviderError(RuntimeError):
    """code: MISSING_CREDENTIALS | AUTH_FAILED | MODEL_UNAVAILABLE | PRO_MODE_UNAVAILABLE |
    BINDING_MISMATCH | RATE_LIMITED | TIMEOUT | NETWORK | BAD_REQUEST | FIXTURE_MISSING | PROVIDER_ERROR"""

    RETRYABLE = {"RATE_LIMITED", "TIMEOUT", "NETWORK"}

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code

    @property
    def retryable(self) -> bool:
        return self.code in self.RETRYABLE


class Provider(Protocol):
    origin: ExecutionOrigin

    def complete(self, request: LLMRequest, timeout: float) -> LLMResponse: ...


def _parse_json(text: str) -> tuple[Optional[dict], Optional[str]]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg} at {exc.pos}"
    if not isinstance(value, dict):
        return None, "top-level JSON must be an object"
    return value, None


class OpenAIResponsesProvider:
    origin = ExecutionOrigin.live

    def __init__(self, binding: ModelBinding, credential_env: str = "OPENAI_API_KEY", client: Any = None):
        self.binding = binding
        self.credential_env = credential_env
        self._client = client

    # The request is assembled in one place so that tests can assert its exact shape.
    def build_request_kwargs(self, request: LLMRequest) -> dict[str, Any]:
        return {
            "model": self.binding.resolved_model,
            "reasoning": {"mode": self.binding.reasoning_mode},
            "input": [
                {"role": "developer", "content": request.developer_text},
                {"role": "user", "content": json.dumps(request.user_payload, ensure_ascii=False)},
            ],
            "text": {"format": {"type": "json_schema", "name": request.schema_name,
                                "schema": request.output_schema, "strict": False}},
            "max_output_tokens": request.max_output_tokens,
            "store": False,
        }

    def client(self, timeout: float) -> Any:
        if self._client is not None:
            return self._client
        key = os.environ.get(self.credential_env)
        if not key:
            raise ProviderError("MISSING_CREDENTIALS", f"environment variable {self.credential_env} is not set")
        import openai  # imported lazily: offline runs never load the SDK

        self._client = openai.OpenAI(api_key=key, timeout=timeout, max_retries=0)
        return self._client

    def complete(self, request: LLMRequest, timeout: float) -> LLMResponse:
        kwargs = self.build_request_kwargs(request)
        assert "effort" not in kwargs["reasoning"]
        try:
            resp = self.client(timeout).responses.create(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:
            raise _map_openai_error(exc) from exc
        returned_model = getattr(resp, "model", None)
        reasoning_obj = getattr(resp, "reasoning", None)
        returned_reasoning: dict[str, Any] = {}
        if reasoning_obj is not None:
            for key in ("mode", "effort"):
                val = getattr(reasoning_obj, key, None) if not isinstance(reasoning_obj, dict) else reasoning_obj.get(key)
                if val is not None:
                    returned_reasoning[key] = val
        if returned_model and not str(returned_model).startswith(self.binding.resolved_model):
            raise ProviderError("BINDING_MISMATCH", f"requested {self.binding.resolved_model}, response reports {returned_model}")
        if returned_reasoning.get("mode") not in (None, self.binding.reasoning_mode):
            raise ProviderError("BINDING_MISMATCH",
                                f"requested reasoning.mode={self.binding.reasoning_mode}, response reports {returned_reasoning['mode']}")
        text = getattr(resp, "output_text", "") or ""
        usage = getattr(resp, "usage", None)
        output, err = _parse_json(text)
        return LLMResponse(
            output=output, raw_text=text, parse_error=err, origin=self.origin,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            returned_model=returned_model, returned_reasoning=returned_reasoning,
            response_id=getattr(resp, "id", None),
        )


def _map_openai_error(exc: Exception) -> ProviderError:
    name = type(exc).__name__
    msg = str(exc)[:300]
    low = msg.lower()
    if name == "AuthenticationError":
        return ProviderError("AUTH_FAILED", msg)
    if name in ("NotFoundError", "PermissionDeniedError"):
        return ProviderError("MODEL_UNAVAILABLE", msg)
    if name == "BadRequestError" and ("reasoning" in low or "mode" in low):
        return ProviderError("PRO_MODE_UNAVAILABLE", msg)
    if name == "BadRequestError":
        return ProviderError("BAD_REQUEST", msg)
    if name == "RateLimitError":
        return ProviderError("RATE_LIMITED", msg)
    if name == "APITimeoutError":
        return ProviderError("TIMEOUT", msg)
    if name == "APIConnectionError" or "networkforbidden" in name.lower():
        return ProviderError("NETWORK", msg)
    return ProviderError("PROVIDER_ERROR", f"{name}: {msg}")


class FixtureProvider:
    """Deterministic, offline responses from ``tests/fixtures/llm/<task_id>/<fixture_key>.json``.

    Clearly labelled ``origin=fixture``. It never imports a network client, needs no
    credentials and never probes model availability.
    """
    origin = ExecutionOrigin.fixture

    def __init__(self, root: Path, task_id: str):
        self.root = Path(root) / task_id

    def complete(self, request: LLMRequest, timeout: float) -> LLMResponse:
        path = self.root / f"{request.fixture_key or request.task_type}.json"
        if not path.exists():
            raise ProviderError("FIXTURE_MISSING", f"no fixture {path.name} for task_type={request.task_type}")
        text = path.read_text(encoding="utf-8")
        output, err = _parse_json(text)
        # Logical usage of a fixture call (~4 chars/token); labelled fixture, never billed.
        return LLMResponse(output=output, raw_text=text, parse_error=err, origin=self.origin,
                           input_tokens=max(1, -(-request.input_chars() // 4)), output_tokens=max(1, len(text) // 4))
