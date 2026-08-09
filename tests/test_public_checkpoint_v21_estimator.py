"""Public-seam tests for the development-only v2.1 checkpoint estimator."""
from __future__ import annotations

import copy
import importlib
import inspect
import unittest

from leakage_attack.v21_config import load_development_config
from leakage_attack.v21_estimator import V21EstimatorError, estimate
from leakage_attack.v2_disclosure import build_transcript, partition_strict_k
from leakage_attack.v2_simulator import simulate_latent_trace


def action(action_id: str, user: str, direction: str, order: int, *, day: int = 0) -> dict:
    return {
        "record_type": "action",
        "action_id": action_id,
        "eligible_id": user,
        "action_type": direction,
        "day": day,
        "within_day_tick": order,
        "global_order": order,
    }


def checkpoint(checkpoint_id: int, shares: int, order: int, *, day: int = 0, rate: int = 1_000_000, assets: int | None = None) -> dict:
    return {
        "record_type": "checkpoint",
        "checkpoint_id": checkpoint_id,
        "release": "checkpoint_totals",
        "day": day,
        "within_day_tick": order,
        "global_order": order,
        "rate": rate,
        "checkpoint_assets": shares if assets is None else assets,
        "checkpoint_shares": shares,
    }


class V21EstimatorPublicSeamTests(unittest.TestCase):
    def test_two_deposits_total_100_are_equal_under_minimum_norm(self):
        transcript = [
            action("a", "u000", "deposit", 0),
            action("b", "u001", "deposit", 1),
            checkpoint(0, 100, 1),
        ]
        result = estimate(transcript, horizon=30)
        self.assertAlmostEqual(result.action_estimates[0].inferred_shares, 50.0, places=9)
        self.assertAlmostEqual(result.action_estimates[1].inferred_shares, 50.0, places=9)
        self.assertAlmostEqual(result.final_positions["u000"], 50.0, places=9)
        self.assertAlmostEqual(result.final_positions["u001"], 50.0, places=9)
        self.assertEqual(result.completed_checkpoint_count, 1)

    def test_same_user_deposit_withdraw_respects_every_prefix_balance(self):
        transcript = [
            action("d", "u000", "deposit", 0), checkpoint(0, 100, 0),
            action("w", "u000", "withdraw", 1), checkpoint(1, 0, 1),
        ]
        result = estimate(transcript, horizon=30)
        values = {item.action_id: item for item in result.action_estimates}
        self.assertAlmostEqual(values["d"].inferred_shares, 100.0, places=8)
        self.assertAlmostEqual(values["w"].inferred_shares, 100.0, places=8)
        self.assertGreaterEqual(values["w"].estimated_balance_before, -1e-8)
        self.assertGreaterEqual(values["w"].estimated_balance_after, -1e-8)
        self.assertAlmostEqual(result.final_positions["u000"], 0.0, places=8)

    def test_later_checkpoint_revises_early_cross_window_estimate_and_reconciles_all_totals(self):
        transcript = [
            action("a", "u000", "deposit", 0, day=0),
            action("b", "u001", "deposit", 1, day=0),
            checkpoint(0, 100, 1, day=0),
            action("w", "u000", "withdraw", 2, day=40),
            checkpoint(1, 0, 2, day=40),
        ]
        early = estimate(transcript, horizon=30)
        late = estimate(transcript, horizon=365)
        early_values = {item.action_id: item.inferred_shares for item in early.action_estimates}
        late_values = {item.action_id: item.inferred_shares for item in late.action_estimates}
        self.assertAlmostEqual(early_values["a"], 50.0, places=8)
        self.assertAlmostEqual(early_values["b"], 50.0, places=8)
        self.assertAlmostEqual(late_values["a"], 100.0, places=7)
        self.assertAlmostEqual(late_values["b"], 0.0, places=7)
        self.assertAlmostEqual(late_values["w"], 100.0, places=7)
        self.assertLessEqual(late.diagnostic.max_checkpoint_residual_normalized, 1e-7)
        self.assertGreaterEqual(late.diagnostic.min_balance_normalized, -1e-7)

    def test_prefix_causality_ignores_later_public_records(self):
        prefix = [action("a", "u000", "deposit", 0, day=0), checkpoint(0, 100, 0, day=0)]
        complete = [
            *prefix,
            action("later", "u001", "deposit", 1, day=90), checkpoint(1, 200, 1, day=90),
        ]
        isolated = estimate(prefix, horizon=30)
        with_future = estimate(complete, horizon=30)
        self.assertEqual(isolated, with_future)

    def test_post_horizon_truth_and_malformed_non_day_fields_are_irrelevant(self):
        prefix = [action("a", "u000", "deposit", 0, day=0), checkpoint(0, 100, 0, day=0)]
        hidden_future = action("hidden", "u001", "deposit", 1, day=90)
        hidden_future["truth_position"] = 99
        malformed_future = {
            "record_type": "not-a-public-record",
            "day": 91,
            "within_day_tick": "not-an-integer",
            "global_order": None,
            "checkpoint_shares": "not-an-integer",
        }
        self.assertEqual(estimate(prefix, horizon=30), estimate([*prefix, hidden_future, malformed_future], horizon=30))

    def test_post_horizon_missing_or_invalid_day_fails_closed(self):
        prefix = [action("a", "u000", "deposit", 0, day=0), checkpoint(0, 100, 0, day=0)]
        missing_day = action("missing", "u001", "deposit", 1, day=90)
        del missing_day["day"]
        invalid_day = action("invalid", "u001", "deposit", 1, day=90)
        invalid_day["day"] = "90"
        for future in (missing_day, invalid_day):
            with self.subTest(future=future):
                with self.assertRaisesRegex(V21EstimatorError, "record day must be an integer"):
                    estimate([*prefix, future], horizon=30)

    def test_no_checkpoint_is_explicit_zero_tail_abstention(self):
        transcript = [action("a", "u000", "deposit", 0), action("w", "u000", "withdraw", 1)]
        result = estimate(transcript, horizon=30)
        self.assertEqual(result.completed_checkpoint_count, 0)
        self.assertEqual(result.diagnostic.status, "tail_only")
        self.assertTrue(all(item.tail_abstention and not item.completed and item.inferred_shares == 0.0 for item in result.action_estimates))
        self.assertEqual(result.final_positions["u000"], 0.0)

    def test_malformed_hidden_or_infeasible_transcript_fails_closed(self):
        leaked = action("a", "u000", "deposit", 0)
        leaked["shares"] = 100
        with self.assertRaises(V21EstimatorError):
            estimate([leaked], horizon=30)
        infeasible = [action("w", "u000", "withdraw", 0), checkpoint(0, 100, 0)]
        with self.assertRaisesRegex(V21EstimatorError, "feasibility"):
            estimate(infeasible, horizon=30)

    def test_oversized_checkpoint_shares_fail_closed_before_solver_conversion(self):
        transcript = [
            action("a", "u000", "deposit", 0),
            checkpoint(0, 10 ** 1000, 0),
        ]
        with self.assertRaisesRegex(V21EstimatorError, "checkpoint share scale cannot be represented"):
            estimate(transcript, horizon=30)

    def test_scale_equivariance_and_deterministic_replay(self):
        base = [action("a", "u000", "deposit", 0), action("b", "u001", "deposit", 1), checkpoint(0, 100, 1)]
        scaled = [action("a", "u000", "deposit", 0), action("b", "u001", "deposit", 1), checkpoint(0, 1000, 1)]
        first = estimate(base, horizon=30)
        second = estimate(base, horizon=30)
        tenfold = estimate(scaled, horizon=30)
        self.assertEqual(first, second)
        for ordinary, enlarged in zip(first.action_estimates, tenfold.action_estimates):
            self.assertAlmostEqual(enlarged.inferred_shares, ordinary.inferred_shares * 10.0, places=7)

    def test_rate_assets_and_private_truth_metamorphisms_do_not_change_output(self):
        public = [action("a", "u000", "deposit", 0), action("b", "u001", "deposit", 1), checkpoint(0, 100, 1)]
        changed = copy.deepcopy(public)
        changed[-1]["rate"] = 17
        changed[-1]["checkpoint_assets"] = 9_999_999_999
        self.assertEqual(estimate(public, horizon=30), estimate(changed, horizon=30))
        # These conflicting private annotations are intentionally not passed to
        # the public seam.  Their shared public projection is byte-for-byte
        # unchanged, so the sealed result is unchanged too.
        private_one = [{**public[0], "shares": 1}, {**public[1], "shares": 99}]
        private_two = [{**public[0], "shares": 99}, {**public[1], "shares": 1}]
        public_one = [{key: value for key, value in item.items() if key != "shares"} for item in private_one] + [public[-1]]
        public_two = [{key: value for key, value in item.items() if key != "shares"} for item in private_two] + [public[-1]]
        self.assertEqual(public_one, public_two)
        self.assertEqual(estimate(public_one, horizon=30), estimate(public_two, horizon=30))

    def test_generated_feasible_public_prefix_does_not_false_fail_during_feasibility(self):
        """Regression: a valid retained seed-41005 public prefix must solve.

        This independently establishes feasibility from the private generator
        only in the test setup: every visible checkpoint equals its source
        cumulative aggregate and every modeled per-user true prefix remains
        nonnegative.  The public-only estimator then receives only the emitted
        transcript.
        """
        resolved = load_development_config()
        trace = simulate_latent_trace(
            dict(resolved.calibration_snapshot.payload),
            seed=41005,
            days=365,
            traffic_mode="known_infrastructure_excluded",
            activation_hazards=resolved.activation_hazards,
        )
        partition = partition_strict_k(trace.events, days=365, k=7)
        transcript = build_transcript(
            trace.events, days=365, partition=partition, release="checkpoint_totals",
        )
        horizon = 180
        visible_checkpoints = [
            record for record in transcript
            if record["record_type"] == "checkpoint" and record["day"] < horizon
        ]
        self.assertEqual(len(visible_checkpoints), 18)
        final_order = visible_checkpoints[-1]["global_order"]
        modeled_truth = [
            event for event in trace.events
            if event["day"] < horizon and event["global_order"] <= final_order
        ]
        source_by_order = {event["global_order"]: event for event in trace.events}
        running_total = 0
        checkpoint_by_order = {record["global_order"]: record for record in visible_checkpoints}
        running_positions: dict[str, int] = {}
        for event in modeled_truth:
            amount = int(event["shares"])
            running_total += amount if event["action_type"] == "deposit" else -amount
            user = str(event["eligible_id"])
            running_positions[user] = running_positions.get(user, 0) + (
                amount if event["action_type"] == "deposit" else -amount
            )
            self.assertGreaterEqual(running_positions[user], 0)
            released = checkpoint_by_order.get(event["global_order"])
            if released is not None:
                self.assertEqual(int(released["checkpoint_shares"]), running_total)
                self.assertEqual(
                    int(released["checkpoint_shares"]),
                    int(source_by_order[event["global_order"]]["aggregate_shares_after"]),
                )
        result = estimate(transcript, horizon=horizon)
        self.assertEqual(result.diagnostic.status, "ok")
        self.assertEqual(result.completed_checkpoint_count, len(visible_checkpoints))

    def test_public_api_has_no_calibration_or_excluded_estimator_dependencies(self):
        module = importlib.import_module("leakage_attack.v21_estimator")
        source = inspect.getsource(module).lower()
        self.assertEqual(list(inspect.signature(estimate).parameters), ["public_transcript", "horizon"])
        for excluded in ("prior", "profile", "nnls", "v3", "rate_only"):
            self.assertNotIn(excluded, source)
        self.assertNotIn("v2_", source)


if __name__ == "__main__":
    unittest.main()
