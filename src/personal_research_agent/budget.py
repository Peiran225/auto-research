"""Budget reservation and settlement (plan §7.1).

Dimensions map to config limits. A reservation is written inside a BEGIN IMMEDIATE
transaction after checking ``reserved(open) + actual(settled) + request <= limit``, so two
workers cannot spend the same balance. Failed attempts are settled like successful ones.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .models import utcnow
from .store import Store

LIMIT_KEYS = {
    "llm_calls": "max_llm_calls",
    "input_tokens": "max_input_tokens_total",
    "output_tokens": "max_output_tokens_total",
    "search_queries": "max_search_queries",
    "full_text_reads": "max_full_text_reads",
    "pilots": "max_pilots",
    "actions": "max_actions",
    "gpu_hours": "gpu_hours",
    "usd": "api_usd",
}


class BudgetExceeded(RuntimeError):
    def __init__(self, dimension: str, requested: float, remaining: float):
        super().__init__(f"budget {dimension}: requested {requested}, remaining {remaining}")
        self.dimension, self.requested, self.remaining = dimension, requested, remaining


@dataclass
class Reservation:
    ids: dict[str, int]
    action_id: Optional[str]
    attempt: int


class Budget:
    def __init__(self, store: Store, limits: dict, deadline_epoch: float):
        self.store = store
        self.limits = {dim: float(limits.get(key, 0) or 0) for dim, key in LIMIT_KEYS.items()}
        self.deadline_epoch = deadline_epoch
        self.action_wall_seconds = float(limits.get("action_wall_seconds", 60))

    # ------------------------------------------------------------------ accounting
    def used(self, dimension: str) -> float:
        row = self.store.conn.execute(
            """SELECT COALESCE(SUM(CASE WHEN state='reserved' THEN reserved
                                         WHEN state='settled' THEN COALESCE(actual, reserved) ELSE 0 END), 0)
               FROM budget WHERE run_id=? AND dimension=?""", (self.store.run_id, dimension)).fetchone()
        return float(row[0])

    def remaining(self, dimension: str) -> float:
        return self.limits[dimension] - self.used(dimension)

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {d: {"limit": self.limits[d], "used": round(self.used(d), 4), "remaining": round(self.remaining(d), 4)}
                for d in self.limits}

    def wall_remaining(self) -> float:
        return self.deadline_epoch - time.time()

    def action_deadline_seconds(self, cleanup_margin: float = 2.0) -> float:
        """Subprocess/backend deadline: min(action cap, remaining run time - cleanup margin)."""
        return max(0.0, min(self.action_wall_seconds, self.wall_remaining() - cleanup_margin))

    # ------------------------------------------------------------------ reserve / settle
    def can_reserve(self, request: dict[str, float]) -> Optional[BudgetExceeded]:
        for dim, amount in request.items():
            if amount <= 0:
                continue
            if dim not in self.limits:
                raise KeyError(f"unknown budget dimension {dim}")
            rem = self.remaining(dim)
            if amount > rem + 1e-9:
                return BudgetExceeded(dim, amount, rem)
        return None

    def reserve(self, request: dict[str, float], action_id: Optional[str], attempt: int = 1,
                cost_type: str = "measured", backend_run_id: Optional[str] = None) -> Reservation:
        with self.store.tx():
            problem = self.can_reserve(request)
            if problem:
                self.store.event("budget_reservation_refused", {"action_id": action_id, "dimension": problem.dimension,
                                                                "requested": problem.requested,
                                                                "remaining": problem.remaining})
                raise problem
            ids: dict[str, int] = {}
            for dim, amount in request.items():
                if amount <= 0:
                    continue
                cur = self.store.conn.execute(
                    """INSERT INTO budget(run_id, action_id, attempt, backend_run_id, dimension, reserved, state,
                                          cost_type, created_at) VALUES (?,?,?,?,?,?, 'reserved', ?, ?)""",
                    (self.store.run_id, action_id, attempt, backend_run_id, dim, float(amount), cost_type, utcnow()))
                ids[dim] = int(cur.lastrowid)
            self.store.event("budget_reserved", {"action_id": action_id, "attempt": attempt, "request": request})
        return Reservation(ids=ids, action_id=action_id, attempt=attempt)

    def settle(self, reservation: Reservation, actual: dict[str, float], cost_type: str | None = None) -> None:
        """Record actual use (possibly above the reservation, e.g. an overrun the provider reported)
        and release the remainder. Idempotent per reservation row."""
        with self.store.tx():
            for dim, row_id in reservation.ids.items():
                row = self.store.conn.execute("SELECT state FROM budget WHERE id=?", (row_id,)).fetchone()
                if row is None or row[0] != "reserved":
                    continue
                value = float(actual.get(dim, 0.0))
                if cost_type:
                    self.store.conn.execute(
                        "UPDATE budget SET actual=?, state='settled', settled_at=?, cost_type=? WHERE id=?",
                        (value, utcnow(), cost_type, row_id))
                else:
                    self.store.conn.execute("UPDATE budget SET actual=?, state='settled', settled_at=? WHERE id=?",
                                            (value, utcnow(), row_id))
            extra = {d: v for d, v in actual.items() if d not in reservation.ids and v}
            for dim, value in extra.items():   # unreserved dimensions that were still consumed
                self.store.conn.execute(
                    """INSERT INTO budget(run_id, action_id, attempt, dimension, reserved, actual, state, cost_type,
                                          created_at, settled_at) VALUES (?,?,?,?,0,?, 'settled', ?, ?, ?)""",
                    (self.store.run_id, reservation.action_id, reservation.attempt, dim, float(value),
                     cost_type or "measured", utcnow(), utcnow()))
            self.store.event("budget_settled", {"action_id": reservation.action_id, "attempt": reservation.attempt,
                                                "actual": actual})

    def open_reservations(self) -> list[tuple]:
        return self.store.conn.execute(
            "SELECT id, action_id, attempt, dimension, reserved FROM budget WHERE run_id=? AND state='reserved'",
            (self.store.run_id,)).fetchall()

    def release_orphans(self, action_ids_done: set[str]) -> int:
        """On resume: reservations of actions that already settled elsewhere are released."""
        n = 0
        with self.store.tx():
            for row_id, action_id, *_ in self.open_reservations():
                if action_id in action_ids_done:
                    self.store.conn.execute("UPDATE budget SET state='released', settled_at=? WHERE id=?",
                                            (utcnow(), row_id))
                    n += 1
        return n
