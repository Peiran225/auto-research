"""Config, task and profile loading with validation (plan §3)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ProfileItem, ResearcherProfile, TasteRule, ExecutionOrigin, stable_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PINNED_V3_COMMIT = "f8ae47d324edcb6c0d430552f1c7729748c0d411"
OFFICIAL_PRO_MODEL = "gpt-6-astra"     # documented GPT-6 Pro mapping as of 2026-11-24 (plan §2.1)


class ConfigError(ValueError):
    pass


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_rounds: int = Field(gt=0)
    max_actions: int = Field(gt=0)
    max_no_change_rounds: int = Field(gt=0)
    max_retries_per_action: int = Field(ge=0)
    max_candidates: int = Field(gt=0)
    max_parallel_actions: int = Field(gt=0)
    max_llm_calls: int = Field(ge=0)
    max_input_tokens_total: int = Field(ge=0)
    max_output_tokens_total: int = Field(ge=0)
    max_search_queries: int = Field(ge=0)
    max_full_text_reads: int = Field(ge=0)
    max_pilots: int = Field(ge=0)
    run_wall_seconds: float = Field(gt=0)
    action_wall_seconds: float = Field(gt=0)
    gpu_hours: float = Field(ge=0)
    api_usd: float = Field(ge=0)


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["fixture", "openai"]
    model: Optional[str] = None
    api: Optional[Literal["responses"]] = None
    requested_product: Optional[str] = None
    reasoning: Optional[dict[str, Any]] = None
    mapping_verified_on: Optional[str] = None
    mapping_sources: list[str] = []
    allow_task_overrides: bool = False
    fallback_models: list[str] = []
    freeze_binding_per_run: bool = True
    credential_env: str = "OPENAI_API_KEY"
    request_timeout_seconds: float = 900
    max_output_tokens_per_call: int = 8000
    pricing: dict[str, Optional[float]] = {}
    # Explicit, recorded deviation from the documented mapping (e.g. gpt-6.2-astra). Still one model
    # per run, Pro mode required, no fallback; the binding marks it as a user choice.
    user_model_override: bool = False
    override_reason: Optional[str] = None

    @property
    def is_official_mapping(self) -> bool:
        return self.model == OFFICIAL_PRO_MODEL

    @model_validator(mode="after")
    def _gpt6_pro(self) -> "LLMConfig":
        if self.provider == "fixture":
            if self.model is not None:
                raise ConfigError("the fixture provider has no model")
            return self
        # The unified binding of plan §2.1. Anything else is a configuration error, not a choice.
        if self.api != "responses":
            raise ConfigError("llm.api must be 'responses'")
        if not self.model or not re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", self.model):
            raise ConfigError("llm.model must be a plain model id")
        if self.model != OFFICIAL_PRO_MODEL:
            if not self.user_model_override or not (self.override_reason or "").strip():
                raise ConfigError(f"llm.model must be {OFFICIAL_PRO_MODEL} (official GPT-6 Pro mapping, plan §2.1); "
                                  "to use another model set llm.user_model_override: true and llm.override_reason")
        elif self.user_model_override:
            raise ConfigError("llm.user_model_override is only for models other than the official mapping")
        reasoning = self.reasoning or {}
        if reasoning.get("mode") != "pro":
            raise ConfigError("llm.reasoning.mode must be 'pro'")
        if "effort" in reasoning:
            raise ConfigError("llm.reasoning.effort must be absent: effort is not the Pro mode (plan §2.1)")
        if set(reasoning) - {"mode"}:
            raise ConfigError(f"unsupported llm.reasoning keys {sorted(set(reasoning) - {'mode'})}")
        if self.fallback_models:
            raise ConfigError("llm.fallback_models must be empty: no silent model fallback")
        if self.allow_task_overrides:
            raise ConfigError("llm.allow_task_overrides must be false")
        if not self.freeze_binding_per_run:
            raise ConfigError("llm.freeze_binding_per_run must be true")
        if not self.requested_product or not self.mapping_verified_on:
            raise ConfigError("llm.requested_product and llm.mapping_verified_on are required")
        return self


class LiteratureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["fixture", "arxiv", "openalex"]
    openalex_mailto_env: Optional[str] = None
    max_chars_per_read: int = 40000      # text sent to the model per read_paper query (whole paper if shorter)
    request_timeout_seconds: float = 30


class BackendConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: Literal["local", "ai_scientist_v3"]
    inherit_frontend_llm: bool = False
    checkout: Optional[str] = None
    pinned_commit: Optional[str] = None
    python: Optional[str] = None
    agsci: Optional[str] = None
    agent: dict[str, Any] = {}
    container_enabled: bool = True
    phases: list[str] = ["investigation", "ablations", "posthoc", "paper"]
    max_idea_cycles: int = 2
    workers: int = 1
    num_replications: int = 1
    harness_evaluation_timeout_seconds: int = 1800
    require_strict_budget: list[str] = []

    @model_validator(mode="after")
    def _v3(self) -> "BackendConfig":
        if self.inherit_frontend_llm:
            raise ConfigError("backend.inherit_frontend_llm must be false: v3 keeps its own agent/model config")
        if self.kind == "ai_scientist_v3":
            if "final_evaluation" in self.phases or "task_drafting" in self.phases:
                raise ConfigError("hand-written tasks must not request task_drafting/final_evaluation (sealed contract phases)")
        return self


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int
    mode: Literal["offline_local", "live"]
    llm: LLMConfig
    literature: LiteratureConfig
    backend: BackendConfig
    decision: dict[str, Any]
    limits: Limits
    reporting: dict[str, Any]

    @model_validator(mode="after")
    def _mode(self) -> "RunConfig":
        if self.mode == "offline_local":
            if self.llm.provider != "fixture":
                raise ConfigError("offline_local forbids external model APIs (llm.provider must be fixture)")
            if self.literature.provider != "fixture":
                raise ConfigError("offline_local forbids networked literature search (literature.provider must be fixture)")
            if self.backend.kind != "local":
                raise ConfigError("offline_local runs only the local backend")
            if self.limits.api_usd != 0:
                raise ConfigError("offline_local has no paid budget (limits.api_usd must be 0)")
        else:
            if self.llm.provider == "fixture" or self.literature.provider == "fixture":
                raise ConfigError("live mode must not use fixture providers")
            if self.limits.api_usd <= 0:
                raise ConfigError("live mode needs a positive limits.api_usd for paid model calls")
        strategy = self.decision.get("strategy", "personalized_loop")
        if strategy not in ("one_shot", "evidence_loop", "personalized_loop"):
            raise ConfigError(f"unknown decision.strategy {strategy}")
        return self

    @property
    def origin(self) -> ExecutionOrigin:
        return ExecutionOrigin.fixture if self.llm.provider == "fixture" else ExecutionOrigin.live


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int
    task_id: str
    idea: str
    target_venues: list[str]
    research_branch: Literal["auto", "theoretical", "empirical", "mixed"]
    metrics: dict[str, Any]
    clarification_requirements: list[str]


def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"file not found: {path}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping")
    return data


def load_config(path: Path) -> RunConfig:
    data = _load_yaml(path)
    try:
        return RunConfig.model_validate(data)
    except ConfigError:
        raise
    except Exception as exc:  # pydantic ValidationError wraps ConfigError text too
        raise ConfigError(f"{path}: {exc}") from exc


def load_task(path: Path) -> TaskSpec:
    try:
        return TaskSpec.model_validate(_load_yaml(path))
    except Exception as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load_profile(path: Path) -> ResearcherProfile:
    data = _load_yaml(path)
    try:
        return ResearcherProfile(
            id=f"profile_{data['profile_id']}",
            origin=ExecutionOrigin.offline_local,
            source=str(path),
            researcher=data["researcher"],
            expertise=[ProfileItem(**e) for e in data.get("expertise", [])],
            research_interests=data.get("research_interests", []),
            taste_rules=[TasteRule(**t) for t in data.get("taste_rules", [])],
            constraints=data.get("constraints", []),
            profile_hash=stable_hash(data),
        )
    except Exception as exc:
        raise ConfigError(f"{path}: {exc}") from exc
