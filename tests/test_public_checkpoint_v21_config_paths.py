"""Config and output-path contract tests for development-only v2.1."""
from __future__ import annotations

import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from leakage_attack.v21_config import (
    CANONICAL_DEVELOPMENT_OUTPUT_ROOT, DEFAULT_CALIBRATION, DEFAULT_CONFIG,
    DEVELOPMENT_SEEDS, HIGHS_PRESOLVE, SCHEMA_VERSION, load_development_config,
)
from leakage_attack.v21_paths import (
    CANONICAL_DEVELOPMENT_ROOT, DIAGNOSTIC_ATTEMPT_1_ROOT,
    EXPERIMENT_ROOT,
    immutable_v1_v2_roots,
    prepare_new_output_root,
    reject_protected_or_existing_output,
    write_new_text,
)


class V21ConfigAndPathsTests(unittest.TestCase):
    def test_frozen_development_config_has_only_the_new_seed_range_and_release(self):
        resolved = load_development_config()
        self.assertEqual(resolved.raw["development_seed_range"], [41001, 41030])
        self.assertEqual(tuple(DEVELOPMENT_SEEDS), tuple(range(41001, 41031)))
        self.assertEqual(resolved.raw["release"], "checkpoint_totals")
        self.assertEqual(resolved.raw["schema_version"], SCHEMA_VERSION)
        self.assertEqual(resolved.raw["canonical_development_output_root"], CANONICAL_DEVELOPMENT_OUTPUT_ROOT)
        self.assertEqual(resolved.raw["evidence_status"], "development_only_nonconfirmatory")
        self.assertFalse(HIGHS_PRESOLVE)
        self.assertFalse(resolved.solver_payload["feasibility"]["presolve"])
        self.assertTrue(resolved.config_snapshot.sha256)
        self.assertTrue(resolved.calibration_snapshot.sha256)

    def test_console_entry_is_registered_in_the_local_package(self):
        payload = tomllib.loads((EXPERIMENT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            payload["project"]["scripts"]["leakage-v21-development"],
            "leakage_attack.v21_development_cli:main",
        )

    def test_dependency_policy_permits_the_pinned_solver_runtime_only(self):
        payload = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        policy = payload["attacker"]["runtime_dependency_policy"]
        for required in ("already pinned NumPy/SciPy runtime", "HiGHS", "SLSQP"):
            self.assertIn(required, policy)
        for prohibited in (
            "additional or new solver packages",
            "native installations",
            "alternate solver backends",
            "solver fallbacks",
        ):
            self.assertIn(prohibited, policy)
            self.assertIn(prohibited, payload["prohibited"])
        self.assertNotIn("native solver dependencies", payload["prohibited"])
        protocol = (EXPERIMENT_ROOT / "V21_PROTOCOL.md").read_text(encoding="utf-8")
        self.assertIn("already pinned NumPy/SciPy", protocol)
        self.assertIn("HiGHS and SLSQP", protocol)
        self.assertNotIn("or native dependencies", protocol)

    def test_config_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            temp = Path(raw)
            payload = json.loads(DEFAULT_CONFIG.read_text())
            payload["calibration_artifact_sha256"] = "0" * 64
            config = temp / "config.json"
            config.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "calibration hash"):
                load_development_config(config, DEFAULT_CALIBRATION)

    def test_deleted_legacy_root_names_and_existing_output_are_refused(self):
        protected = immutable_v1_v2_roots()
        self.assertEqual(
            {root.name for root in protected},
            {
                "stage_b_k_only_confirmatory_100",
                "stage_b_k_only_confirmatory_100_precleanup_integrity",
            },
        )
        for root in protected:
            self.assertFalse(root.exists())
            with self.subTest(root=root.name):
                with self.assertRaises(ValueError):
                    reject_protected_or_existing_output(root)
                with self.assertRaises(ValueError):
                    reject_protected_or_existing_output(root / "child")
        deleted_v2_name = EXPERIMENT_ROOT / "results" / "stage_b_repeated_aggregate_nnls_v2_confirmatory_100"
        self.assertFalse(deleted_v2_name.exists())
        with self.assertRaises(ValueError):
            reject_protected_or_existing_output(deleted_v2_name)
        with self.assertRaises(ValueError):
            reject_protected_or_existing_output(deleted_v2_name / "child")
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "already-exists"
            output.mkdir()
            with self.assertRaises(ValueError):
                reject_protected_or_existing_output(output)
        with self.assertRaisesRegex(ValueError, "diagnostic attempt 1"):
            reject_protected_or_existing_output(DIAGNOSTIC_ATTEMPT_1_ROOT)
        self.assertEqual(CANONICAL_DEVELOPMENT_ROOT, EXPERIMENT_ROOT / "results" / "public_checkpoint_min_norm_v21_development_30_r2")

    def test_exclusive_root_creation_rejects_symlink_and_existing_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            temp = Path(raw)
            target = temp / "target"
            target.mkdir()
            link = temp / "link"
            os.symlink(target, link)
            with self.assertRaises(ValueError):
                prepare_new_output_root(link)
            created = temp / "fresh"
            prepare_new_output_root(created)
            self.assertTrue(created.is_dir())
            written = write_new_text(created, "artifact.txt", "complete\n")
            self.assertEqual(written.read_text(encoding="utf-8"), "complete\n")
            with self.assertRaises(FileExistsError):
                # The low-level O_EXCL writer refuses an existing final name.
                write_new_text(created, "artifact.txt", "replacement\n")
            with self.assertRaises(ValueError):
                prepare_new_output_root(created)


if __name__ == "__main__":
    unittest.main()
