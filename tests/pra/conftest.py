import os
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", message=".*shadows an attribute in parent.*")

from personal_research_agent.budget import Budget  # noqa: E402
from personal_research_agent.config import PROJECT_ROOT  # noqa: E402
from personal_research_agent.models import (  # noqa: E402
    Assessment, AssessmentState, CandidateRevision, Evidence, EvidenceKind, EvidenceLink, ExecutionOrigin, Level,
    LinkRelation, VerificationStatus,
)
from personal_research_agent.store import Store  # noqa: E402

ROOT = PROJECT_ROOT
LIMITS = dict(max_rounds=6, max_actions=20, max_no_change_rounds=2, max_retries_per_action=1, max_candidates=6,
              max_parallel_actions=2, max_llm_calls=40, max_input_tokens_total=200000, max_output_tokens_total=80000,
              max_search_queries=24, max_full_text_reads=12, max_pilots=3, run_wall_seconds=300,
              action_wall_seconds=60, gpu_hours=0, api_usd=0)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "state.sqlite", "t")
    yield s
    s.close()


@pytest.fixture
def budget(store) -> Budget:
    import time
    return Budget(store, dict(LIMITS), time.time() + 300)


@pytest.fixture
def runs_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "runs"
    monkeypatch.setenv("PRA_RUNS_ROOT", str(root))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return root


def rev(cid="CAND-A", version=1, status="active", claims=None, branch="theoretical", parent=None, **kw):
    return CandidateRevision(id=f"rev_{cid}_v{version}", origin=ExecutionOrigin.fixture, source="test", candidate_id=cid,
                             version=version, parent_revision_id=parent, title=cid, problem_scope="s", hypothesis="h",
                             mechanism="m", increment="i", claims=claims or [{"id": "C1", "statement": "x", "scope": "general"}],
                             abandon_conditions=["a"], research_branch=branch, status=status, **kw)


def evidence(eid, group="g1", kind=EvidenceKind.computation, ns="computation", verified=True, locator="loc", source="s1", obs="o"):
    return Evidence(id=eid, origin=ExecutionOrigin.offline_local, source="test", kind=kind, namespace=ns, source_id=source,
                    source_version="v1", locator=locator, content_hash=f"h-{eid}", observation=obs, same_source_group=group,
                    verification_status=VerificationStatus.verified if verified else VerificationStatus.unverified)


def link(lid, eid, rid, rel=LinkRelation.supports, claim="C1"):
    return EvidenceLink(id=lid, origin=ExecutionOrigin.offline_local, source="test", evidence_id=eid,
                        candidate_revision_id=rid, claim_id=claim, relation=rel, applicability="test")


def assess(rid, dim, level=None, ev=("e1",), cid="CAND-A"):
    state = AssessmentState.known if level else AssessmentState.unknown
    return Assessment(id=f"asm_{rid}_{dim}", origin=ExecutionOrigin.fixture, source="test", subject_type="candidate",
                      subject_id=cid, subject_revision=rid, dimension=dim, state=state,
                      judgment=Level(level) if level else None, evidence_ids=list(ev) if level else [], rationale="r")


def run_cli(*args: str) -> tuple[int, str]:
    from typer.testing import CliRunner
    from personal_research_agent.cli import app

    res = CliRunner().invoke(app, list(args))
    return res.exit_code, res.output
