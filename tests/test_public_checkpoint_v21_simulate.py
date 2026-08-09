"""Development-matrix and unchanged-v2-reuse tests for v2.1 orchestration."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from leakage_attack.v21_config import HORIZONS, K_VALUES, TRAFFIC_MODES, load_development_config
from leakage_attack.v21_simulate import run_seed_artifacts
from leakage_attack.v2_config import canonical_json_sha256
from leakage_attack.v2_disclosure import checkpoint_schedule, partition_strict_k
from leakage_attack.v2_simulator import LatentTrace, simulate_latent_trace


def fake_trace(seed: int, traffic_mode: str, *, shares: int = 10) -> LatentTrace:
    positions = {f"u{index:03d}": 0 for index in range(100)}
    events = []
    aggregate = 0
    for index in range(50):
        user = f"u{index:03d}"
        positions[user] = shares
        aggregate += shares
        events.append({
            "action_id": f"fixture-{traffic_mode}-{index}", "day": 0, "within_day_tick": index,
            "global_order": index, "eligible_id": user, "action_type": "deposit", "shares": shares,
            "assets": shares, "position_before": 0, "position_after": shares, "rate": 1_000_000,
            "full_withdraw": False, "profile_log_shares": 0.0, "residual_log": 0.0,
            "aggregate_shares_after": aggregate, "aggregate_assets_after": aggregate,
            "activation_event": True, "withdrawal_reselected": False, "withdrawal_converted": False,
        })
    return LatentTrace(
        seed=seed, traffic_mode=traffic_mode, rates=[1_000_000] * 365,
        daily_counts=[50] + [0] * 364, profiles={}, events=events, final_positions=positions,
        diagnostics={"full_withdrawals": 0, "withdrawal_reselections": 0, "withdrawal_conversions": 0},
    )


class V21SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolved = load_development_config()
        def patched(calibration, *, seed, days, traffic_mode, activation_hazards):
            return fake_trace(seed, traffic_mode)
        with patch("leakage_attack.v21_simulate.simulate_latent_trace", side_effect=patched):
            cls.artifacts = run_seed_artifacts(41001, resolved=cls.resolved)

    def test_seed_has_exactly_120_checkpoint_total_cells_and_no_second_treatment(self):
        rows = self.artifacts.metrics
        self.assertEqual(len(rows), 120)
        self.assertEqual(
            {(row["traffic_mode"], row["k"], row["release"], row["horizon_day"]) for row in rows},
            {(traffic, k, "checkpoint_totals", horizon) for traffic in TRAFFIC_MODES for k in K_VALUES for horizon in HORIZONS},
        )
        self.assertEqual({row["release"] for row in rows}, {"checkpoint_totals"})
        self.assertTrue(all(row["solver_status"] == "ok" for row in rows))

    def test_oversized_checkpoint_shares_mark_cells_failed_without_aborting_seed(self):
        def patched(calibration, *, seed, days, traffic_mode, activation_hazards):
            return fake_trace(seed, traffic_mode, shares=10 ** 1000)
        with patch("leakage_attack.v21_simulate.simulate_latent_trace", side_effect=patched):
            artifacts = run_seed_artifacts(41001, resolved=self.resolved)
        self.assertEqual(len(artifacts.metrics), 120)
        self.assertTrue(all(row["solver_status"] == "failed" for row in artifacts.metrics))
        self.assertTrue(all("checkpoint share scale cannot be represented" in row["solver_message"] for row in artifacts.metrics))
        self.assertEqual(len(artifacts.public_action_estimates), 0)
        self.assertEqual(len(artifacts.private_truth_joins), 0)

    def test_trace_is_reused_across_k_horizons_and_source_has_separate_reuse_hashes(self):
        for traffic in TRAFFIC_MODES:
            subset = [row for row in self.artifacts.metrics if row["traffic_mode"] == traffic]
            self.assertEqual(len({row["latent_trace_hash"] for row in subset}), 1)
            self.assertEqual(len({row["action_trace_hash"] for row in subset}), 1)
            self.assertEqual(len(subset), len(K_VALUES) * len(HORIZONS))
        manifest = self.artifacts.source_manifest
        self.assertEqual(manifest["source_scope"], "v21_python_only")
        self.assertTrue(manifest["v21_files"])
        self.assertTrue(manifest["reused_unchanged_v2_modules"])
        self.assertTrue(self.artifacts.provenance["reused_v2_modules_sha256"])

    def test_fixed_v2_trace_and_schedule_regression_remain_unchanged(self):
        calibration = json.loads((Path(__file__).resolve().parents[1] / "results" / "v2_empirical_inputs.json").read_text())
        trace = simulate_latent_trace(calibration, seed=10001, traffic_mode="known_infrastructure_excluded")
        public = [
            {key: event[key] for key in ("action_id", "day", "within_day_tick", "global_order", "eligible_id", "action_type")}
            for event in trace.events
        ]
        schedule = checkpoint_schedule(partition_strict_k(trace.events, days=365, k=7))
        self.assertEqual(len(trace.events), 419)
        self.assertEqual(canonical_json_sha256(public), "9fc612220822a55309d6ea56e32079a4b701234bbe7450951fd72a1a77d60dc3")
        self.assertEqual(canonical_json_sha256(schedule), "e0f71f9ecf4c175d0fa9c2589a00cdf82d1139ba906bc9057123c604f3fb8674")

    def test_retained_strict_k_partition_is_not_mutated_by_v21_execution(self):
        trace = fake_trace(41001, "known_infrastructure_excluded")
        before = checkpoint_schedule(partition_strict_k(trace.events, days=365, k=5))
        after = checkpoint_schedule(partition_strict_k(trace.events, days=365, k=5))
        self.assertEqual(before, after)
        self.assertEqual(before[0]["action_ids"], [event["action_id"] for event in trace.events[:5]])


if __name__ == "__main__":
    unittest.main()
