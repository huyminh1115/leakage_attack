"""Descriptive-only summary tests for v2.1 development metrics."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from leakage_attack.v21_config import HORIZONS, K_VALUES, TRAFFIC_MODES
from leakage_attack.v21_simulate import METRIC_COLUMNS, SCHEMA_VERSION
from leakage_attack.v21_summarize import SUMMARY_COLUMNS, summarize_rows, summarize_to_directory, validate_matrix


def metric(seed: int, traffic: str, k: int, horizon: int) -> dict:
    row = {
        "schema_version": SCHEMA_VERSION, "phase": "development", "traffic_mode": traffic,
        "seed": seed, "k": k, "release": "checkpoint_totals", "horizon_day": horizon,
        "latent_trace_hash": f"latent-{seed}-{traffic}", "action_trace_hash": f"actions-{seed}-{traffic}",
        "checkpoint_schedule_hash": f"schedule-{seed}-{traffic}-{k}",
        "config_sha256": "a" * 64, "semantic_config_sha256": "b" * 64, "calibration_sha256": "c" * 64,
        "source_code_fingerprint": "d" * 64, "reused_v2_modules_sha256": "e" * 64,
        "dependency_lock_sha256": "f" * 64, "solver_fingerprint": "0" * 64,
        "solver_status": "ok", "solver_message": "ok", "solver_runtime_seconds": 0.25,
        "public_action_count": 10, "completed_checkpoint_count": 2, "modeled_action_count": 8,
        "tail_action_count": 2, "active_eligible_participants": 1, "position_within_10pct": 0.1,
        "completed_operation_count": 8, "completed_operation_within_10pct": 0.2,
        "tail_operation_count": 2, "tail_operation_within_10pct": 0.0,
        "all_operation_count": 10, "all_operation_within_10pct": 0.16,
    }
    assert tuple(row) == METRIC_COLUMNS
    return row


class V21SummaryTests(unittest.TestCase):
    def test_descriptive_summary_covers_exact_matrix_and_has_no_selection_fields(self):
        rows = [metric(41001, traffic, k, horizon) for traffic in TRAFFIC_MODES for k in K_VALUES for horizon in HORIZONS]
        self.assertEqual(validate_matrix(rows), [41001])
        summary = summarize_rows(rows)
        self.assertTrue(summary)
        self.assertTrue(all(tuple(row) == SUMMARY_COLUMNS for row in summary))
        metrics = {row["metric"] for row in summary}
        self.assertIn("position_within_10pct", metrics)
        self.assertIn("completed_operation_within_10pct", metrics)
        self.assertIn("tail_action_rate", metrics)
        self.assertIn("solver_failure_fraction", metrics)
        self.assertFalse(any("select" in name or "qualif" in name for row in summary for name in row))
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "external-summary"
            metadata = summarize_to_directory(rows, output=root)
            self.assertTrue(metadata["external_safe"])
            rendered = (root / "development_summary.csv").read_text(encoding="utf-8")
            self.assertNotIn("truth_", rendered)
            self.assertNotIn("action_id", rendered)

    def test_tail_only_abstention_is_valid_not_a_solver_failure(self):
        rows = [metric(41001, traffic, k, horizon) for traffic in TRAFFIC_MODES for k in K_VALUES for horizon in HORIZONS]
        tail = rows[0]
        tail.update({
            "solver_status": "tail_only", "position_within_10pct": 0.0,
            "completed_operation_count": 0, "completed_operation_within_10pct": 0.0,
            "tail_operation_count": 10, "tail_operation_within_10pct": 0.0,
            "all_operation_count": 10, "all_operation_within_10pct": 0.0,
            "tail_action_count": 10, "public_action_count": 10,
        })
        summary = summarize_rows(rows)
        group = [row for row in summary if row["traffic_mode"] == tail["traffic_mode"] and row["k"] == tail["k"] and row["horizon_day"] == tail["horizon_day"]]
        failure = next(row for row in group if row["metric"] == "solver_failure_fraction")
        position = next(row for row in group if row["metric"] == "position_within_10pct")
        self.assertEqual(failure["mean"], 0.0)
        self.assertEqual(position["n_successful"], 1)

    def test_failed_cell_is_counted_not_scored_or_dropped(self):
        rows = [metric(41001, traffic, k, horizon) for traffic in TRAFFIC_MODES for k in K_VALUES for horizon in HORIZONS]
        failed = rows[0]
        failed.update({
            "solver_status": "failed", "position_within_10pct": "", "completed_operation_within_10pct": "",
            "tail_operation_within_10pct": "", "all_operation_within_10pct": "", "tail_action_count": "",
            "public_action_count": "", "solver_runtime_seconds": 0.5,
        })
        summary = summarize_rows(rows)
        group = [row for row in summary if row["traffic_mode"] == failed["traffic_mode"] and row["k"] == failed["k"] and row["horizon_day"] == failed["horizon_day"]]
        failure = next(row for row in group if row["metric"] == "solver_failure_fraction")
        position = next(row for row in group if row["metric"] == "position_within_10pct")
        self.assertEqual(failure["mean"], 1.0)
        self.assertEqual(position["n_successful"], 0)
        self.assertEqual(position["mean"], "")


if __name__ == "__main__":
    unittest.main()
