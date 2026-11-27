"""The single LLM call path: binding check, budget reservation, bounded retry, usage, events.

Every self-built call (queries, compression, JSON repair, evidence checks, theory notes) goes
through ``LLMGateway.call``. There is no per-task model selection and no fallback chain.
"""
from __future__ import annotations

import sys
import time
from typing import Callable, Optional

from ..budget import Budget, BudgetExceeded
from ..models import ExecutionOrigin, ModelBinding
from ..store import Store
from .providers import LLMRequest, LLMResponse, Provider, ProviderError


class LLMGateway:
    def __init__(self, provider: Provider, store: Store, budget: Budget, binding: Optional[ModelBinding],
                 max_retries: int, pricing: dict | None = None, sleep=time.sleep,
                 request_timeout: Optional[float] = None, heartbeat_seconds: float = 30.0,
                 log: Optional[Callable[[str], None]] = None):
        if provider.origin == ExecutionOrigin.live and binding is None:
            raise ValueError("live calls require the run's ModelBinding")
        if provider.origin == ExecutionOrigin.fixture and binding is not None:
            raise ValueError("fixture calls must not carry a real ModelBinding")
        if binding is not None and getattr(provider, "binding", None) is not None:
            if provider.binding.binding_hash != binding.binding_hash:  # type: ignore[attr-defined]
                raise ValueError("provider binding differs from the run binding")
        self.provider, self.store, self.budget, self.binding = provider, store, budget, binding
        self.max_retries = max_retries
        self.pricing = pricing or {}
        self.sleep = sleep
        self.request_timeout = request_timeout
        self.heartbeat_seconds = heartbeat_seconds
        self.log = log or (lambda m: print(m, file=sys.stderr, flush=True))

    @property
    def origin(self) -> ExecutionOrigin:
        return self.provider.origin

    def _usd(self, input_tokens: float, output_tokens: float) -> Optional[float]:
        pin, pout = self.pricing.get("input_per_mtok"), self.pricing.get("output_per_mtok")
        if pin is None or pout is None:
            return None
        return input_tokens / 1e6 * pin + output_tokens / 1e6 * pout

    def call(self, request: LLMRequest, action_id: Optional[str]) -> LLMResponse:
        attempt = 0
        last: Optional[ProviderError] = None
        fixture = self.origin == ExecutionOrigin.fixture
        cost_type = "fixture" if fixture else "actual"
        while attempt <= self.max_retries:
            attempt += 1
            request_dims = {"llm_calls": 1, "input_tokens": request.input_token_estimate(),
                            "output_tokens": request.max_output_tokens}
            usd_cap = None if fixture else self._usd(request_dims["input_tokens"], request_dims["output_tokens"])
            if usd_cap is not None:
                request_dims["usd"] = usd_cap
            timeout = self.budget.action_deadline_seconds()
            if self.request_timeout:
                timeout = min(timeout, self.request_timeout)
            if timeout <= 0:
                raise ProviderError("TIMEOUT", "no run time left for a model call")
            try:
                reservation = self.budget.reserve(request_dims, action_id, attempt,
                                                  cost_type=cost_type if usd_cap is not None or fixture else "unpriced")
            except BudgetExceeded:
                raise
            started = time.time()
            calls = f"{self.budget.used('llm_calls'):.0f}/{self.budget.limits['llm_calls']:.0f}"
            last_beat = [started]

            def progress(status: str, elapsed: float, response_id: Optional[str] = None,
                         _task=request.task_type, _attempt=attempt) -> None:
                if response_id and status == "submitted":
                    self.store.event("llm_request_submitted", {"action_id": action_id, "task_type": _task,
                                                               "attempt": _attempt, "response_id": response_id})
                if time.time() - last_beat[0] >= self.heartbeat_seconds:
                    last_beat[0] = time.time()
                    self.log(f"[pra] waiting for model: task={_task} attempt={_attempt} status={status} "
                             f"elapsed={elapsed:.0f}s timeout={timeout:.0f}s llm_calls={calls}")

            if hasattr(self.provider, "progress"):
                self.provider.progress = progress
            try:
                response = self.provider.complete(request, timeout=timeout)
            except ProviderError as err:
                # Failed attempts are still charged: one call, the input we sent, no output tokens.
                self.budget.settle(reservation, {"llm_calls": 1, "input_tokens": request_dims["input_tokens"],
                                                 "output_tokens": 0, "usd": usd_cap or 0.0})
                self.store.event("llm_call_failed", {"action_id": action_id, "task_type": request.task_type,
                                                     "attempt": attempt, "code": err.code, "error": str(err)[:300],
                                                     "binding_hash": self.binding.binding_hash if self.binding else None})
                last = err
                if not err.retryable or attempt > self.max_retries:
                    raise
                self.sleep(min(2 ** attempt, 30))
                continue
            usd = None if fixture else self._usd(response.input_tokens, response.output_tokens)
            self.budget.settle(reservation, {"llm_calls": 1, "input_tokens": response.input_tokens,
                                             "output_tokens": response.output_tokens,
                                             **({"usd": usd} if usd is not None else {})})
            self.store.event("llm_call", {
                "action_id": action_id, "task_type": request.task_type, "attempt": attempt,
                "origin": response.origin.value, "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens, "seconds": round(time.time() - started, 3),
                "binding_hash": self.binding.binding_hash if self.binding else None,
                "returned_model": response.returned_model, "returned_reasoning": response.returned_reasoning,
                "response_id": response.response_id, "cost_type": cost_type if usd is not None or fixture else "unpriced",
            })
            if self.binding is not None and (response.returned_model or response.returned_reasoning):
                meta = {"returned_model": response.returned_model, "returned_reasoning": response.returned_reasoning}
                if meta not in self.binding.runtime_metadata:
                    self.binding.runtime_metadata.append(meta)
            return response
        assert last is not None
        raise last
