"""Frozen development-only configuration for the minimal public checkpoint v2.1 study.

This module deliberately owns a new ``v21_*`` lineage.  It does not amend the
historical v2 config or source fingerprint.  Calibration remains private
synthetic-generator input; the estimator never imports this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = "public_checkpoint_min_norm_v21_r2"
CANONICAL_DEVELOPMENT_OUTPUT_ROOT = "results/public_checkpoint_min_norm_v21_development_30_r2"
DAYS = 365
POPULATION_SIZE = 100
K_VALUES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30, 40, 50)
HORIZONS = (30, 90, 180, 365)
TRAFFIC_MODES = ("known_infrastructure_excluded", "all_addresses")
RELEASE = "checkpoint_totals"
DEVELOPMENT_SEEDS = tuple(range(41001, 41031))
NORMALIZED_CONSTRAINT_TOLERANCE = 1.0e-7
SLSQP_FTOL = 1.0e-9
SLSQP_MAXITER = 1000
# In the pinned SciPy 1.11.4/HiGHS build, presolve incorrectly rejects a
# subset of valid cumulative-prefix models.  The fixed development heuristic
# therefore uses the same highs-ds backend with presolve explicitly disabled.
HIGHS_PRESOLVE = False

EXPERIMENT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = EXPERIMENT_ROOT / "config" / "public_checkpoint_min_norm_v21.development.json"
DEFAULT_CALIBRATION = EXPERIMENT_ROOT / "results" / "v2_empirical_inputs.json"


@dataclass(frozen=True)
class JsonSnapshot:
    """Bytes and parsed object captured through one no-follow descriptor."""

    path: Path
    raw_bytes: bytes
    sha256: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ResolvedV21Config:
    """The typed development contract recorded with each v2.1 artifact."""

    raw: Mapping[str, Any]
    config_snapshot: JsonSnapshot
    calibration_snapshot: JsonSnapshot
    activation_hazards: Mapping[str, float]
    solver_payload: Mapping[str, Any]
    semantic_config_sha256: str


def canonical_json_sha256(value: Any) -> str:
    """Return a stable hash for a JSON-compatible semantic value."""

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_json_file(path: str | Path, *, label: str) -> JsonSnapshot:
    """Read one regular JSON file without following its final symlink.

    The configuration/calibration inputs are stable local files rather than
    evidence roots.  This compact no-follow check prevents a simple pathname
    swap from combining a checksum for one input with semantics from another.
    """

    source = Path(path)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ValueError("v2.1 snapshots require O_NOFOLLOW support")
    try:
        listed = os.lstat(source)
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing: {source}") from error
    if stat.S_ISLNK(listed.st_mode) or not stat.S_ISREG(listed.st_mode):
        raise ValueError(f"{label} must be a regular non-symlink file: {source}")
    descriptor: int | None = None
    try:
        descriptor = os.open(source, os.O_RDONLY | no_follow)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) != (listed.st_dev, listed.st_ino):
            raise ValueError(f"{label} changed while opening: {source}")
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1 << 20)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise ValueError(f"{label} changed while reading: {source}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    raw = b"".join(chunks)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not UTF-8 JSON: {source}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return JsonSnapshot(
        path=source.resolve(), raw_bytes=raw, sha256=hashlib.sha256(raw).hexdigest(),
        payload=MappingProxyType(payload),
    )


def actual_solver_payload() -> dict[str, Any]:
    """Describe only the pinned numerical libraries used by the public heuristic."""

    import numpy
    import scipy

    return {
        "numpy_version": numpy.__version__,
        "scipy_version": scipy.__version__,
        "feasibility": {
            "library": "scipy.optimize.linprog", "method": "highs-ds", "presolve": HIGHS_PRESOLVE,
        },
        "tie_break": {
            "library": "scipy.optimize.minimize",
            "method": "SLSQP",
            "analytic_gradient": True,
            "analytic_constraint_jacobian": True,
            "ftol": SLSQP_FTOL,
            "maxiter": SLSQP_MAXITER,
        },
        "normalized_constraint_tolerance": NORMALIZED_CONSTRAINT_TOLERANCE,
    }


def _require_int_list(config: Mapping[str, Any], name: str, expected: tuple[int, ...]) -> None:
    value = config.get(name)
    if not isinstance(value, list) or any(type(item) is not int for item in value) or tuple(value) != expected:
        raise ValueError(f"v2.1 config {name} differs from the frozen development contract")


def _require_mapping(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = config.get(name)
    if not isinstance(value, Mapping):
        raise ValueError(f"v2.1 config {name} must be an object")
    return value


def validate_development_config(
    config_snapshot: JsonSnapshot,
    calibration_snapshot: JsonSnapshot,
) -> ResolvedV21Config:
    """Fail closed unless a config is exactly the declared v2.1 dev contract."""

    config = config_snapshot.payload
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("v2.1 config schema version mismatch")
    if config.get("evidence_status") != "development_only_nonconfirmatory":
        raise ValueError("v2.1 only supports development-only execution")
    if config.get("canonical_development_output_root") != CANONICAL_DEVELOPMENT_OUTPUT_ROOT:
        raise ValueError("v2.1 canonical development output root differs from the corrected r2 contract")
    if config.get("days") != DAYS or config.get("population_size") != POPULATION_SIZE:
        raise ValueError("v2.1 dimensions differ from frozen development contract")
    _require_int_list(config, "development_seed_range", (DEVELOPMENT_SEEDS[0], DEVELOPMENT_SEEDS[-1]))
    _require_int_list(config, "k_values", K_VALUES)
    _require_int_list(config, "horizons", HORIZONS)
    if config.get("traffic_modes") != list(TRAFFIC_MODES) or config.get("release") != RELEASE:
        raise ValueError("v2.1 public domain differs from frozen development contract")
    if config.get("calibration_artifact_sha256") != calibration_snapshot.sha256:
        raise ValueError("v2.1 calibration hash does not bind the supplied private generator input")
    generator = _require_mapping(config, "generator")
    hazards = _require_mapping(generator, "activation_hazards")
    if set(hazards) != set(TRAFFIC_MODES):
        raise ValueError("v2.1 activation hazards must cover both traffic modes")
    normalized_hazards: dict[str, float] = {}
    for mode in TRAFFIC_MODES:
        value = hazards[mode]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"v2.1 activation hazard for {mode} is invalid")
        normalized_hazards[mode] = float(value)
    attacker = _require_mapping(config, "attacker")
    if attacker.get("magnitude_domain") != "continuous_nonnegative_microshares":
        raise ValueError("v2.1 must use continuous nonnegative action magnitudes")
    if attacker.get("tail_policy") != "actions after the last completed checkpoint through the horizon receive zero abstention and do not update positions":
        raise ValueError("v2.1 tail abstention policy mismatch")
    feasibility = _require_mapping(attacker, "feasibility_solver")
    tie_break = _require_mapping(attacker, "tie_break_solver")
    expected_solver = actual_solver_payload()
    if feasibility != expected_solver["feasibility"] or tie_break != expected_solver["tie_break"]:
        raise ValueError("v2.1 numerical solver declaration mismatch")
    tolerance = attacker.get("normalized_constraint_tolerance")
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or float(tolerance) != NORMALIZED_CONSTRAINT_TOLERANCE:
        raise ValueError("v2.1 normalized constraint tolerance mismatch")
    semantic = {
        "schema_version": SCHEMA_VERSION,
        "evidence_status": config["evidence_status"],
        "canonical_development_output_root": CANONICAL_DEVELOPMENT_OUTPUT_ROOT,
        "days": DAYS,
        "population_size": POPULATION_SIZE,
        "development_seed_range": list(DEVELOPMENT_SEEDS),
        "k_values": list(K_VALUES),
        "horizons": list(HORIZONS),
        "traffic_modes": list(TRAFFIC_MODES),
        "release": RELEASE,
        "calibration_artifact_sha256": calibration_snapshot.sha256,
        "activation_hazards": normalized_hazards,
        "attacker": dict(attacker),
        "solver": expected_solver,
    }
    return ResolvedV21Config(
        raw=MappingProxyType(dict(config)), config_snapshot=config_snapshot,
        calibration_snapshot=calibration_snapshot,
        activation_hazards=MappingProxyType(normalized_hazards),
        solver_payload=MappingProxyType(expected_solver),
        semantic_config_sha256=canonical_json_sha256(semantic),
    )


def load_development_config(
    config_path: str | Path = DEFAULT_CONFIG,
    calibration_path: str | Path = DEFAULT_CALIBRATION,
) -> ResolvedV21Config:
    """Capture and validate the only executable v2.1 configuration class."""

    config = snapshot_json_file(config_path, label="v2.1 development config")
    calibration = snapshot_json_file(calibration_path, label="v2.1 private calibration")
    return validate_development_config(config, calibration)


__all__ = [
    "CANONICAL_DEVELOPMENT_OUTPUT_ROOT", "DAYS", "DEFAULT_CALIBRATION", "DEFAULT_CONFIG",
    "DEVELOPMENT_SEEDS", "EXPERIMENT_ROOT", "HIGHS_PRESOLVE", "HORIZONS", "K_VALUES", "NORMALIZED_CONSTRAINT_TOLERANCE", "POPULATION_SIZE", "RELEASE",
    "ResolvedV21Config", "SCHEMA_VERSION", "SLSQP_FTOL", "SLSQP_MAXITER", "TRAFFIC_MODES",
    "actual_solver_payload", "canonical_json_sha256", "file_sha256", "load_development_config",
    "snapshot_json_file", "validate_development_config",
]
