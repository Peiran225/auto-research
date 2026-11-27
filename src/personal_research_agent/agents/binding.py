"""Unified GPT-6 Pro ModelBinding (plan §2.1).

The binding is created once per run from the validated config and frozen: every self-built
live call references it, and ``resume`` reuses the stored binding instead of re-resolving
"latest". The mapping itself (GPT-6 Pro -> gpt-6-astra + reasoning.mode=pro) is recorded with
its sources and with how it was re-checked at binding time.
"""
from __future__ import annotations

import datetime as dt
import importlib.metadata
from typing import Any, Optional

from ..config import LLMConfig
from ..models import ExecutionOrigin, ModelBinding

S11 = "https://help.openai.com/en/articles/20001354-gpt-6-and-other-models-in-chatgpt"
S12 = "https://developers.openai.com/api/docs/models/gpt-6-astra"
S13 = "https://developers.openai.com/api/docs/guides/reasoning#reasoning-mode"


def sdk_version() -> Optional[str]:
    try:
        return importlib.metadata.version("openai")
    except importlib.metadata.PackageNotFoundError:
        return None


def sdk_mapping_evidence() -> dict[str, Any]:
    """What the installed SDK itself declares (offline evidence; not account availability)."""
    out: dict[str, Any] = {"sdk_version": sdk_version()}
    try:
        from openai.types.shared.chat_model import ChatModel  # noqa: F401
        import typing

        import openai.types.shared.chat_model as cm
        models = set(typing.get_args(cm.ChatModel)) if hasattr(cm, "ChatModel") else set()
        flat: set[str] = set()
        for m in models:
            flat |= set(typing.get_args(m)) or {m}
        out["sdk_lists_gpt_6_astra"] = "gpt-6-astra" in flat
        out["sdk_lists_gpt_6_pro_id"] = any(str(m).startswith(("gpt-6-pro", "gpt-6.2-pro")) for m in flat)
    except Exception as exc:  # pragma: no cover - depends on SDK layout
        out["sdk_model_list_error"] = type(exc).__name__
    try:
        import typing

        from openai.types.shared_params.reasoning import Reasoning
        hints = typing.get_type_hints(Reasoning)
        mode_args = str(hints.get("mode"))
        out["sdk_reasoning_has_mode"] = "mode" in hints
        out["sdk_reasoning_mode_declares_pro"] = "'pro'" in mode_args
    except Exception as exc:  # pragma: no cover
        out["sdk_reasoning_error"] = type(exc).__name__
    return out


def build_binding(llm: LLMConfig, run_id: str, mapping_check: dict[str, Any]) -> ModelBinding:
    if llm.provider != "openai":
        raise ValueError("bindings exist only for real providers; fixture runs have none")
    return ModelBinding(
        id=f"binding_{run_id}",
        origin=ExecutionOrigin.live,
        source="config.llm (plan §2.1 mapping)" if llm.is_official_mapping else "config.llm (user model override)",
        requested_product=llm.requested_product or "",
        provider="openai",
        api="responses",
        resolved_model=llm.model or "",
        reasoning_mode=(llm.reasoning or {}).get("mode", ""),
        requested_effort=None,          # not sent; the server default applies and is not guessed
        effective_effort=None,
        sdk_name="openai-python",
        sdk_version=sdk_version(),
        mapping_verified_on=llm.mapping_verified_on or "",
        mapping_sources=llm.mapping_sources or [S11, S12, S13],
        mapping_check={**mapping_check, "bound_on": dt.date.today().isoformat(),
                       "model_choice": ("official GPT-6 Pro mapping (plan §2.1)" if llm.is_official_mapping else
                                        f"USER OVERRIDE, not the documented GPT-6 Pro mapping: {llm.override_reason}")},
    )
