"""Researcher capability, preferences and their separation from scientific value (plan §4.2).

Familiarity is computed from the profile only and stored in ``Concept.existing_capability``;
it never changes a concept's field importance or a candidate's scientific value. An unfamiliar
concept that matters to the field yields a learning task.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Concept, Level, ResearcherProfile


def _norm(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def capability_for(concept_names: list[str], profile: ResearcherProfile) -> tuple[Level, str]:
    """Stated (unverified) expertise that matches the concept -> medium; otherwise low.
    'high' is reserved for capabilities verified against the researcher's papers."""
    words = set().union(*(_norm(n) for n in concept_names)) if concept_names else set()
    best, best_overlap = None, 0
    for item in profile.expertise:
        name_words = _norm(item.name)
        overlap = len(words & name_words)
        # a match needs every word of a short expertise name, or at least two words of a longer one
        if overlap and overlap >= min(2, len(name_words)) and overlap > best_overlap:
            best, best_overlap = item, overlap
    if best is None:
        return Level.low, "no matching expertise record in the profile"
    level = Level.high if best.verified else Level.medium
    return level, f"profile expertise '{best.name}' ({'verified' if best.verified else 'stated, not verified'}; source {best.source})"


@dataclass
class LearningTask:
    concept: str
    reason: str
    field_importance: Level


def learning_tasks(concepts: list[Concept]) -> list[LearningTask]:
    out = []
    for c in concepts:
        if c.existing_capability == Level.low and c.field_importance in (Level.high, Level.medium):
            out.append(LearningTask(c.canonical_name, f"needed for: {c.role}; profile shows no matching expertise",
                                    c.field_importance))
    return out


def taste_material(profile: ResearcherProfile, strategy: str) -> list[dict]:
    """Taste rules are passed to queries only in the personalized strategy."""
    if strategy != "personalized_loop":
        return []
    return [t.model_dump() for t in profile.taste_rules]
