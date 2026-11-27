# Acceptance log

Executed on 2026-11-25T02:04Z in the cloud container (Python 3.13.18, commit base b1cc5ae).

## `python -m pytest -q`

```text
..................................................                       [100%]
50 passed in 5.94s
exit code: 0
```

## `pra doctor --config configs/offline.yaml`

```text
{
  "mode": "offline_local",
  "strategy": "personalized_loop",
  "limits": {
    "max_rounds": 6,
    "max_actions": 20,
    "max_no_change_rounds": 2,
    "max_retries_per_action": 1,
    "max_candidates": 6,
    "max_parallel_actions": 2,
    "max_llm_calls": 40,
    "max_input_tokens_total": 200000,
    "max_output_tokens_total": 80000,
    "max_search_queries": 24,
    "max_full_text_reads": 12,
    "max_pilots": 3,
    "run_wall_seconds": 300.0,
    "action_wall_seconds": 60.0,
    "gpu_hours": 0.0,
    "api_usd": 0.0
  },
  "llm": {
    "provider": "fixture",
    "note": "offline fixture; no model probe, no credentials, no network"
  },
  "literature": {
    "provider": "fixture"
  },
  "backend": {
    "backend": "local",
    "available": true,
    "capabilities": {
      "theory_counterexample": true,
      "cpu_pilot": true,
      "formal_empirical": false,
      "gpu": false,
      "writing": "deterministic templates only",
      "pilots": [
        "mdp_counterexample",
        "mdp_exact_enumeration",
        "nested_vs_alternating"
      ]
    },
    "budget_dimensions": {
      "wall_seconds": "strict",
      "pilots": "strict",
      "usd": "strict (no paid calls)"
    },
    "missing": [],
    "versions": {
      "python": "3.13.18"
    }
  },
  "environment": {
    "pdflatex": false,
    "docker": true,
    "gpu": false,
    "python": "3.13.18"
  },
  "missing": []
exit code: 0
```

## `pra run --task examples/mdp_uncertainty.yaml --profile profiles/peiran.yaml --config configs/offline.yaml --run-id acceptance_mdp`

```text
{
  "run_id": "acceptance_mdp",
  "phase": "finish",
  "operation_status": "completed",
  "planning_outcome": "inconclusive",
  "research_outcome": "refuted",
  "manuscript_status": "not_generated",
  "stop_reason": "no_available_action",
  "rounds": 5,
  "recommended": null,
  "error": null,
  "reports": "runs/acceptance_mdp/reports/"
}
exit code: 0
```

## `pra verify --run-id acceptance_mdp`

```text
{
  "run_id": "acceptance_mdp",
  "ok": true,
  "problems": [],
  "checks": {
    "references": "ok",
    "artifacts": 3,
    "claims": 3,
    "budget_used": {
      "llm_calls": 21.0,
      "input_tokens": 45132.0,
      "output_tokens": 19494.0,
      "search_queries": 5.0,
      "full_text_reads": 3.0,
      "actions": 4.0,
      "pilots": 3.0
    },
    "status": {
      "operation": "completed",
      "planning": "inconclusive",
      "research": "refuted",
      "manuscript": "not_generated"
    }
  }
}
exit code: 0
```

## `pra run --task examples/world_model.yaml --profile profiles/peiran.yaml --config configs/offline.yaml --run-id acceptance_world_model`

```text
{
  "run_id": "acceptance_world_model",
  "phase": "finish",
  "operation_status": "completed",
  "planning_outcome": "inconclusive",
  "research_outcome": "not_run",
  "manuscript_status": "not_generated",
  "stop_reason": "no_available_action",
  "rounds": 2,
  "recommended": null,
  "error": null,
  "reports": "runs/acceptance_world_model/reports/"
}
exit code: 0
```

## `pra verify --run-id acceptance_world_model`

```text
{
  "run_id": "acceptance_world_model",
  "ok": true,
  "problems": [],
  "checks": {
    "references": "ok",
    "artifacts": 1,
    "claims": 2,
    "budget_used": {
      "llm_calls": 13.0,
      "input_tokens": 18940.0,
      "output_tokens": 10420.0,
      "search_queries": 5.0,
      "full_text_reads": 3.0,
      "actions": 1.0,
      "pilots": 1.0
    },
    "status": {
      "operation": "completed",
      "planning": "inconclusive",
      "research": "not_run",
      "manuscript": "not_generated"
    }
  }
}
exit code: 0
```

## `pra status --run-id acceptance_mdp`

```text
{
  "run_id": "acceptance_mdp",
  "phase": "finish",
  "operation_status": "completed",
  "planning_outcome": "inconclusive",
  "research_outcome": "refuted",
  "manuscript_status": "not_generated",
  "stop_reason": "no_available_action",
  "rounds": 5,
  "recommended": null,
  "error": null,
  "reports": "runs/acceptance_mdp/reports/",
  "budget": {
    "llm_calls": {
      "limit": 40.0,
      "used": 21.0,
      "remaining": 19.0
    },
    "input_tokens": {
      "limit": 200000.0,
      "used": 45132.0,
      "remaining": 154868.0
    },
    "output_tokens": {
      "limit": 80000.0,
      "used": 19494.0,
      "remaining": 60506.0
    },
    "search_queries": {
      "limit": 24.0,
      "used": 5.0,
      "remaining": 19.0
    },
    "full_text_reads": {
      "limit": 12.0,
      "used": 3.0,
      "remaining": 9.0
    },
    "pilots": {
      "limit": 3.0,
      "used": 3.0,
      "remaining": 0.0
    },
    "actions": {
      "limit": 20.0,
      "used": 4.0,
      "remaining": 16.0
    },
    "gpu_hours": {
      "limit": 0.0,
      "used": 0.0,
      "remaining": 0.0
    },
    "usd": {
      "limit": 0.0,
      "used": 0.0,
      "remaining": 0.0
    }
  },
  "notes": [
exit code: 0
```

## `pra resume --run-id acceptance_mdp`

```text
run acceptance_mdp already completed; nothing to resume
{
  "run_id": "acceptance_mdp",
  "phase": "finish",
  "operation_status": "completed",
  "planning_outcome": "inconclusive",
  "research_outcome": "refuted",
  "manuscript_status": "not_generated",
  "stop_reason": "no_available_action",
  "rounds": 5,
  "recommended": null,
  "error": null,
  "reports": "runs/acceptance_mdp/reports/"
}
exit code: 0
```

## `pra report --run-id acceptance_mdp`

```text
{
  "decision_report.md": "present",
  "research_note.md": "present",
  "research_spec.json": "present",
  "claim_evidence_map.json": "present",
  "audit_report.md": "present",
  "manuscript": "missing: manuscript_missing: no AI-Scientist-v3 paper phase ran in this run (local backend); only a deterministic research note was written",
  "references.bib": "not_applicable: no verified live literature records",
  "manuscript.tex": "not_generated: no upstream manuscript source",
  "pdf": "not_generated: no manuscript source and no LaTeX toolchain in this environment"
}
exit code: 0
```

## `pra run --task examples/mdp_uncertainty.yaml --profile profiles/peiran.yaml --config configs/offline.yaml --strategy one_shot --run-id compare_one_shot`

```text
{
  "run_id": "compare_one_shot",
  "phase": "finish",
  "operation_status": "completed",
  "planning_outcome": "inconclusive",
  "research_outcome": "not_run",
  "manuscript_status": "not_generated",
  "stop_reason": "no_available_action",
  "rounds": 0,
  "recommended": null,
  "error": null,
  "reports": "runs/compare_one_shot/reports/"
}
exit code: 0
```

## `pra run --task examples/mdp_uncertainty.yaml --profile profiles/peiran.yaml --config configs/offline.yaml --strategy evidence_loop --run-id compare_evidence_loop`

```text
{
  "run_id": "compare_evidence_loop",
  "phase": "finish",
  "operation_status": "completed",
  "planning_outcome": "inconclusive",
  "research_outcome": "refuted",
  "manuscript_status": "not_generated",
  "stop_reason": "no_available_action",
  "rounds": 5,
  "recommended": null,
  "error": null,
  "reports": "runs/compare_evidence_loop/reports/"
}
exit code: 0
```

## `pra run --task examples/mdp_uncertainty.yaml --profile profiles/peiran.yaml --config configs/offline.yaml --strategy personalized_loop --run-id compare_personalized_loop`

```text
{
  "run_id": "compare_personalized_loop",
  "phase": "finish",
  "operation_status": "completed",
  "planning_outcome": "inconclusive",
  "research_outcome": "refuted",
  "manuscript_status": "not_generated",
  "stop_reason": "no_available_action",
  "rounds": 5,
  "recommended": null,
  "error": null,
  "reports": "runs/compare_personalized_loop/reports/"
}
exit code: 0
```

## `pra compare compare_one_shot compare_evidence_loop compare_personalized_loop`

```text
{
  "same_limits": true,
  "runs": [
    {
      "run_id": "compare_one_shot",
      "strategy": "one_shot",
      "planning_outcome": "inconclusive",
      "research_outcome": "not_run",
      "stop_reason": "no_available_action",
      "known_judgements": 5,
      "traceable_rate": 1.0,
      "wrong_references": 0,
      "rejudgements_after_counterevidence": 3,
      "candidates_total": 3,
      "candidates_surviving": 2,
      "human_interventions": 0,
      "rounds": 0,
      "llm_calls": 10.0,
      "execution_origins": [
        "fixture"
      ]
    },
    {
      "run_id": "compare_evidence_loop",
      "strategy": "evidence_loop",
      "planning_outcome": "inconclusive",
      "research_outcome": "refuted",
      "stop_reason": "no_available_action",
      "known_judgements": 7,
      "traceable_rate": 1.0,
      "wrong_references": 0,
      "rejudgements_after_counterevidence": 6,
      "candidates_total": 3,
      "candidates_surviving": 2,
      "human_interventions": 0,
      "rounds": 5,
      "llm_calls": 21.0,
      "execution_origins": [
        "fixture"
      ]
    },
    {
      "run_id": "compare_personalized_loop",
      "strategy": "personalized_loop",
      "planning_outcome": "inconclusive",
      "research_outcome": "refuted",
      "stop_reason": "no_available_action",
      "known_judgements": 7,
      "traceable_rate": 1.0,
      "wrong_references": 0,
      "rejudgements_after_counterevidence": 6,
      "candidates_total": 3,
      "candidates_surviving": 2,
      "human_interventions": 0,
      "rounds": 5,
      "llm_calls": 21.0,
      "execution_origins": [
        "fixture"
      ]
    }
exit code: 0
```


## Interrupt / resume check (`kill -9` of the pra process)

```text
state after SIGKILL: acquire_evidence running 2
[pra] reconciled 1 interrupted action(s), released 0 orphan reservation(s)
[pra] acceptance_resume phase=acquire_evidence round=2 actions=2/20 llm_calls=14/40 wall_left=300s
[pra] acceptance_resume phase=finish round=5 actions=5/20 llm_calls=22/40 wall_left=300s
  "operation_status": "completed",
  "research_outcome": "refuted",
exit code: 0
settled usage: {'actions': 5.0, 'full_text_reads': 3.0, 'input_tokens': 55157.0, 'llm_calls': 22.0, 'output_tokens': 19494.0, 'pilots': 3.0, 'search_queries': 5.0}
open reservations: 0
resume events: ['stale_lock_taken_over', 'action_reconciled', 'round_resumed', 'decision_reused']
duplicate fingerprints: 0
  "ok": true,
    "references": "ok",
```
