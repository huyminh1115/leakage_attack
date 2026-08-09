"""Truth-side evaluation tests for v2.1 sealed public estimates."""
from __future__ import annotations

import unittest
from types import MappingProxyType

from leakage_attack.v21_estimator import V21ActionEstimate, V21EstimateResult, V21SolveDiagnostic
from leakage_attack.v21_evaluate import evaluate


def public_estimate(action_id: str, user: str, direction: str, amount: float, *, completed: bool, order: int) -> V21ActionEstimate:
    return V21ActionEstimate(
        action_id=action_id, eligible_id=user, action_type=direction, day=0, within_day_tick=order,
        global_order=order, inferred_shares=amount, completed=completed, tail_abstention=not completed,
        estimated_balance_before=0.0, estimated_balance_after=amount if direction == "deposit" else 0.0,
    )


def result(positions: dict[str, float], estimates: list[V21ActionEstimate]) -> V21EstimateResult:
    return V21EstimateResult(
        final_positions=MappingProxyType(positions), action_estimates=tuple(estimates), completed_checkpoint_count=1,
        diagnostic=V21SolveDiagnostic("ok", "test", 1, 1, 0, 1.0, 0.0, 0.0, 0.0, 0, 0, 1),
    )


def truth(action_id: str, user: str, direction: str, shares: int, after: int, order: int) -> dict:
    return {
        "action_id": action_id, "eligible_id": user, "action_type": direction,
        "shares": shares, "position_after": after, "global_order": order,
    }


class V21EvaluatorTests(unittest.TestCase):
    def test_p10_is_inclusive_and_tail_and_all_are_separate(self):
        sealed = result(
            {"u000": 90.0, "u001": 0.0},
            [
                public_estimate("a", "u000", "deposit", 90.0, completed=True, order=0),
                public_estimate("b", "u001", "deposit", 0.0, completed=False, order=1),
            ],
        )
        outcome = evaluate(
            [truth("a", "u000", "deposit", 100, 100, 0), truth("b", "u001", "deposit", 100, 100, 1)],
            sealed,
        )
        self.assertEqual(outcome.position.active_eligible_participants, 2)
        self.assertEqual(outcome.position.within_10pct, 0.5)
        self.assertEqual(outcome.operation.completed_count, 1)
        self.assertEqual(outcome.operation.completed_within_10pct, 1.0)
        self.assertEqual(outcome.operation.tail_count, 1)
        self.assertEqual(outcome.operation.tail_within_10pct, 0.0)
        self.assertEqual(outcome.operation.all_count, 2)
        self.assertEqual(outcome.operation.all_within_10pct, 0.5)

    def test_zero_active_position_denominator_is_zero_not_dropped(self):
        sealed = result({"u000": 0.0}, [public_estimate("w", "u000", "withdraw", 0.0, completed=True, order=0)])
        outcome = evaluate([truth("w", "u000", "withdraw", 10, 0, 0)], sealed)
        self.assertEqual(outcome.position.active_eligible_participants, 0)
        self.assertEqual(outcome.position.within_10pct, 0.0)


if __name__ == "__main__":
    unittest.main()
