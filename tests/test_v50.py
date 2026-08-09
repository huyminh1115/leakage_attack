from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import nnls

from leakage_attack import v50_cli
from leakage_attack.v50 import (
    ACTORS, LAMBDA_MULTIPLIERS, Operation, PublicRelease, TruthSnapshot,
    _ridge_nonnegative, build_releases, estimate_public, evaluate, generate_trace,
    lambda_grid, run_seed_k,
)


class V50Tests(unittest.TestCase):
    def test_generator_is_reproducible_and_preserves_true_and_count_feasibility(self):
        first = generate_trace(50001, operations=300)
        self.assertEqual(first, generate_trace(50001, operations=300))
        balances = {actor: 0 for actor in ACTORS}; counts = {actor: [0, 0] for actor in ACTORS}
        for event in first:
            if event.direction == "deposit": balances[event.actor] += event.amount; counts[event.actor][0] += 1
            else: balances[event.actor] -= event.amount; counts[event.actor][1] += 1
            self.assertGreaterEqual(balances[event.actor], 0)
            self.assertGreaterEqual(counts[event.actor][0], counts[event.actor][1])

    def test_strict_k_resets_and_censors_tail(self):
        trace = generate_trace(50002, operations=50)
        built = build_releases(trace, 3)
        self.assertTrue(built.public)
        self.assertTrue(all(len(row.actors) == 3 for row in built.public))
        self.assertLess(built.censored_tail_actor_count, 3)
        self.assertTrue(all(len(set(row.actors)) == 3 for row in built.public))

    def test_public_prefix_is_causal_and_rejects_negative_count_feature(self):
        trace = generate_trace(50003, operations=200)
        releases = build_releases(trace, 2).public
        self.assertGreater(len(releases), 12)
        prefix = estimate_public(releases[:12])
        extended = estimate_public(releases[:30])
        self.assertEqual(prefix, extended[:12])
        bad = PublicRelease(0, ("a000",), 1, (0,) * 100, (1,) + (0,) * 99)
        with self.assertRaisesRegex(ValueError, "count prefix"):
            estimate_public([bad])

    def test_public_transcript_rejects_regressing_cumulative_counts(self):
        base_deposits = (1,) + (0,) * 99
        base_withdrawals = (0,) * 100
        baseline = PublicRelease(0, ("a000",), 1, base_deposits, base_withdrawals)
        decreasing_deposits = PublicRelease(1, ("a000",), 1, (0,) * 100, base_withdrawals)
        with self.assertRaisesRegex(ValueError, "deposit count regresses"):
            estimate_public((baseline, decreasing_deposits))

        withdrawal_baseline = PublicRelease(0, ("a000",), 1, (2,) + (0,) * 99, (1,) + (0,) * 99)
        decreasing_withdrawals = PublicRelease(1, ("a000",), 2, (2,) + (0,) * 99, (0,) * 100)
        with self.assertRaisesRegex(ValueError, "withdrawal count regresses"):
            estimate_public((withdrawal_baseline, decreasing_withdrawals))

    def test_hand_authored_trace_has_exact_reset_reentry_aggregates_and_censored_tail(self):
        trace = (
            Operation(0, "a000", "deposit", 1, 0, 10, 10),
            Operation(1, "a001", "deposit", 1, 0, 20, 20),
            Operation(2, "a000", "withdraw", 1, 1, 5, 5),
            Operation(3, "a002", "deposit", 1, 0, 7, 7),
            Operation(4, "a001", "withdraw", 1, 1, 20, 0),
        )
        built = build_releases(trace, 2)
        self.assertEqual(tuple(row.actors for row in built.public), (("a000", "a001"), ("a000", "a002")))
        self.assertEqual(tuple(row.aggregate_shares for row in built.public), (30, 12))
        self.assertEqual(built.public[1].withdrawal_counts[:3], (1, 0, 0))
        self.assertEqual(built.truth[1].balances[:3], (5, 20, 7))
        self.assertEqual(built.censored_tail_actor_count, 1)

    def test_lambda_grid_and_warmup_choose_largest_then_score_active_only(self):
        grid = lambda_grid(np.zeros((100, 100)))
        self.assertEqual(grid[-1], 10.0)
        releases = (
            PublicRelease(0, ("a000",), 100, (1,) + (0,) * 99, (0,) * 100),
            PublicRelease(1, ("a000",), 200, (2,) + (0,) * 99, (0,) * 100),
        )
        public = estimate_public(releases)
        self.assertTrue(all(item.warmup for item in public))
        self.assertTrue(all(item.lambda_value == grid[-1] for item in public))
        # Equal public prediction losses must select the larger candidate after warm-up.
        tied = tuple(PublicRelease(index, ("a000",), 0, (index + 1,) + (0,) * 99, (0,) * 100) for index in range(11))
        self.assertEqual(estimate_public(tied)[10].lambda_value, 38.5)
        truth = (TruthSnapshot((100,) + (0,) * 99), TruthSnapshot((200,) + (0,) * 99))
        scored = evaluate(releases, truth, public)
        self.assertEqual(scored[0].active_actor_count, 1)
        self.assertEqual(scored[0].zero_actor_count, 99)
        self.assertAlmostEqual(scored[0].s10, 1.0 - scored[0].l10)
        self.assertTrue(all(value >= 0 for value in scored[0].predictions))

    def test_rolling_loss_selection_uses_latest_fifty_releases(self):
        releases = tuple(
            PublicRelease(index, ("a000",), 1 if index < 100 else 10, (1,) + (0,) * 99, (0,) * 100)
            for index in range(150)
        )

        def deterministic_solver(gram, response, ridge, initial=None):
            result = np.zeros(100, dtype=float)
            result[0] = ridge
            return result

        with patch("leakage_attack.v50.lambda_grid", return_value=LAMBDA_MULTIPLIERS), patch(
            "leakage_attack.v50._ridge_nonnegative", side_effect=deterministic_solver
        ):
            scores = estimate_public(releases)
        self.assertEqual(scores[-1].lambda_value, 10.0)
        all_history_losses = {
            candidate: float(np.mean([(candidate - release.aggregate_shares) ** 2 for release in releases]))
            for candidate in LAMBDA_MULTIPLIERS
        }
        self.assertEqual(min(all_history_losses, key=all_history_losses.get), 1.0)

    def test_projected_ridge_matches_diagonal_nonnegative_oracle(self):
        gram = np.zeros((100, 100), dtype=float)
        gram[0, 0] = 4.0
        gram[1, 1] = 2.0
        response = np.zeros(100, dtype=float)
        response[:2] = (10.0, -5.0)
        actual = _ridge_nonnegative(gram, response, 2.0)
        expected = np.zeros(100, dtype=float)
        expected[0] = 10.0 / 6.0
        np.testing.assert_allclose(actual, expected, atol=1e-7, rtol=1e-7)

    def test_nonnegative_ridge_matches_correlated_nnls_oracle(self):
        rng = np.random.default_rng(412)
        base = rng.normal(size=(80, 1))
        # A valid non-negative, highly correlated public design.  The former
        # fixed 120-step projected-gradient solver remains far from this oracle.
        design = np.maximum(base @ np.ones((1, 100)) + 0.02 * rng.normal(size=(80, 100)) + 3.0, 0.0)
        profile = np.zeros(100, dtype=float)
        profile[:6] = (2.0, 4.0, 6.0, 3.0, 1.0, 5.0)
        response_vector = design @ profile + 0.1 * rng.normal(size=80)
        ridge = 1e-3
        actual = _ridge_nonnegative(design.T @ design, design.T @ response_vector, ridge)
        trusted_design = np.vstack((design, math.sqrt(ridge) * np.eye(100)))
        trusted_response = np.concatenate((response_vector, np.zeros(100)))
        expected, _ = nnls(trusted_design, trusted_response, maxiter=3000)
        np.testing.assert_allclose(actual, expected, atol=1e-7, rtol=1e-7)

    def test_cli_writes_schemas_and_reuses_one_trace_for_multiple_k_values(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "v50-output"
            with patch("leakage_attack.v50_cli.generate_trace", wraps=generate_trace) as mocked_generate_trace:
                exit_code = v50_cli.main([
                    "--output", str(output), "--seed", "50001", "--k", "1", "--k", "2", "--operations", "30",
                ])
            self.assertEqual(exit_code, 0)
            mocked_generate_trace.assert_called_once_with(50001, operations=30)
            expected_paths = {"run_summary.csv", "snapshot_trajectory.csv", "run_metadata.json"}
            self.assertEqual({path.name for path in output.iterdir()}, expected_paths)
            with (output / "run_summary.csv").open(newline="", encoding="utf-8") as handle:
                summary = list(csv.DictReader(handle))
            self.assertEqual({int(row["k"]) for row in summary}, {1, 2})
            self.assertEqual(set(summary[0]), {"seed", "k", "release_count", "censored_tail_actor_count", "primary_l10", "primary_s10"})
            with (output / "snapshot_trajectory.csv").open(newline="", encoding="utf-8") as handle:
                trajectory = list(csv.DictReader(handle))
            self.assertTrue(trajectory)
            self.assertEqual(set(trajectory[0]), {"seed", "k", "snapshot", "warmup", "lambda", "l10", "s10", "truth_active_actor_count", "zero_actor_count"})
            metadata = json.loads((output / "run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["schema_version"], "v50_experimental_r1")
            self.assertEqual(metadata["seeds"], [50001])
            self.assertEqual(metadata["k_values"], [1, 2])

    def test_run_excludes_first_ten_snapshots_from_primary_summary(self):
        result = run_seed_k(50004, 1, operations=30)
        self.assertEqual(result.release_count, 30)
        self.assertTrue(all(row.warmup for row in result.snapshot_scores[:10]))
        self.assertTrue(all(not row.warmup for row in result.snapshot_scores[10:]))
        self.assertIsNotNone(result.primary_l10)
        self.assertAlmostEqual(result.primary_s10, 1.0 - result.primary_l10)


if __name__ == "__main__": unittest.main()
