"""Filesystem lifecycle tests for the isolated v2.1 development runner."""
from __future__ import annotations

import csv
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from leakage_attack.v21_config import load_development_config
from leakage_attack.v21_development import run_development
from leakage_attack.v21_paths import CANONICAL_DEVELOPMENT_ROOT
from leakage_attack.v21_simulate import (
    METRIC_COLUMNS, PRIVATE_TRUTH_JOIN_COLUMNS, PUBLIC_ACTION_ESTIMATE_COLUMNS, SCHEMA_VERSION,
    SOLVER_DIAGNOSTIC_COLUMNS, TRAFFIC_DIAGNOSTIC_COLUMNS, V21SeedArtifacts,
)


def row(columns: tuple[str, ...], **values: object) -> dict:
    return {name: values.get(name, "") for name in columns}


def fixture(seed: int) -> V21SeedArtifacts:
    provenance = {
        "config_sha256": "a" * 64, "semantic_config_sha256": "b" * 64, "calibration_sha256": "c" * 64,
        "source_code_fingerprint": "d" * 64, "reused_v2_modules_sha256": "e" * 64,
        "dependency_lock_sha256": "f" * 64, "solver_fingerprint": "0" * 64,
    }
    base = {
        "schema_version": SCHEMA_VERSION, "phase": "development",
        "traffic_mode": "known_infrastructure_excluded", "seed": seed, "k": 1,
        "release": "checkpoint_totals", "horizon_day": 30, "latent_trace_hash": "latent",
        "action_trace_hash": "actions", "checkpoint_schedule_hash": "schedule", **provenance,
    }
    metrics = [row(METRIC_COLUMNS, **base, solver_status="ok", solver_message="ok", solver_runtime_seconds=0.1,
        public_action_count=1, completed_checkpoint_count=1, modeled_action_count=1, tail_action_count=0,
        active_eligible_participants=1, position_within_10pct=1.0, completed_operation_count=1,
        completed_operation_within_10pct=1.0, tail_operation_count=0, tail_operation_within_10pct=0.0,
        all_operation_count=1, all_operation_within_10pct=1.0)]
    diagnostics = [row(SOLVER_DIAGNOSTIC_COLUMNS, **base, solver_status="ok", solver_message="ok", solver_runtime_seconds=0.1,
        modeled_action_count=1, completed_checkpoint_count=1, tail_action_count=0, scale_m=1.0, objective=0.5,
        max_checkpoint_residual_normalized=0.0, min_balance_normalized=0.0, linprog_status=0, slsqp_status=0,
        slsqp_iterations=1)]
    public = [row(PUBLIC_ACTION_ESTIMATE_COLUMNS, **{key: base[key] for key in ("schema_version", "phase", "traffic_mode", "seed", "k", "release", "horizon_day")},
        action_id="a", eligible_id="u000", action_type="deposit", day=0, within_day_tick=0, global_order=0,
        inferred_shares=1.0, completed=True, tail_abstention=False, estimated_balance_before=0.0, estimated_balance_after=1.0)]
    private = [row(PRIVATE_TRUTH_JOIN_COLUMNS, **{key: base[key] for key in ("schema_version", "phase", "traffic_mode", "seed", "k", "release", "horizon_day")},
        action_id="a", truth_shares=1, truth_assets=1, truth_position_before=0, truth_position_after=1,
        truth_full_withdraw=False, inferred_shares=1.0, completed=True, tail_abstention=False)]
    traffic = [row(TRAFFIC_DIAGNOSTIC_COLUMNS, **{key: base[key] for key in ("schema_version", "phase", "traffic_mode", "seed", "latent_trace_hash", "action_trace_hash", *provenance)},
        daily_event_count=1, realized_distinct_identifiers=1, realized_deposit_count=1, realized_withdraw_count=0)]
    return V21SeedArtifacts(metrics, diagnostics, public, private, traffic, provenance, {"fixture": True})


class V21DevelopmentLifecycleTests(unittest.TestCase):
    def test_canonical_root_rejects_a_subset_before_creation(self):
        resolved = load_development_config()
        with self.assertRaisesRegex(ValueError, "complete 41001"):
            run_development(output=CANONICAL_DEVELOPMENT_ROOT, seeds=(41001,), resolved=resolved)

    def test_runner_writes_separated_public_private_trees_and_never_overwrites(self):
        resolved = load_development_config()
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "development"
            with patch("leakage_attack.v21_development.run_seed_artifacts", side_effect=lambda seed, resolved: fixture(seed)):
                metadata = run_development(output=output, seeds=(41001,), resolved=resolved)
            self.assertFalse(metadata["complete_development_domain"])
            self.assertTrue((output / "public" / "metrics.csv").is_file())
            self.assertTrue((output / "private" / "seed_41001" / "truth_join.csv.gz").is_file())
            public_text = (output / "public" / "metrics.csv").read_text(encoding="utf-8")
            self.assertNotIn("truth_shares", public_text)
            with gzip.open(output / "private" / "seed_41001" / "truth_join.csv.gz", "rt", encoding="utf-8") as handle:
                self.assertIn("truth_shares", handle.readline())
            self.assertTrue((output / "SHA256SUMS").is_file())
            with self.assertRaises(ValueError):
                run_development(output=output, seeds=(41001,), resolved=resolved)


if __name__ == "__main__":
    unittest.main()
