"""Frozen names, runtime constants, and execution-contract validation for v2.

The JSON file is a provenance commitment, not a decorative copy of defaults.
Activation hazards are read from the resolved config at runtime.  Other
scientific and numerical settings are deliberately implemented as frozen code
constants and must match the corresponding JSON declaration before any output
is created.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = "repeated_aggregate_nnls_v2"
UNIT = 1_000_000
DAYS = 365
POPULATION_SIZE = 100
K_VALUES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30, 40, 50)
RELEASES = ("checkpoint_totals", "rate_only")
TRAFFIC_MODES = ("known_infrastructure_excluded", "all_addresses")
HORIZONS = (30, 90, 180, 365)
DEVELOPMENT_SEEDS = tuple(range(10001, 10031))
CONFIRMATORY_SEEDS = tuple(range(20001, 20101))

# Environment constants declared in the versioned JSON contract.
MOVING_BLOCK_DAYS = 7
MOVING_BLOCK_BOUNDARY = "circular"
UNIFORM_TIME_REPRESENTATION = "integer nanoseconds in simulated UTC day"
UNIFORM_TIME_TIE_BREAK = "global action order"
DEFAULT_SHRINKAGE_ADDEND = 5
DEFAULT_RESIDUAL_LOG_CLIP = 1.3862943611198906  # ln(4)
DEFAULT_ACTIVATION_HAZARDS = {
    "known_infrastructure_excluded": 0.44972923398017883,
    "all_addresses": 0.21393129229545593,
}
ACTIVATION_HAZARD_FUNCTION = (
    "per scheduled event after first observed action; select an inactive "
    "candidate with probability hazard, but retain it inactive until it "
    "executes an action; otherwise recurrence-select an observed identifier"
)
FULL_WITHDRAW_PROBABILITY = 0.02

# The attacker has a public enrollment-domain assumption, not a dynamically
# discovered feature set.  Keep this ordering stable in every history matrix.
PROFILE_DIRECTIONS = ("deposit", "withdraw")
ELIGIBLE_IDS = tuple(f"u{index:03d}" for index in range(POPULATION_SIZE))
PROFILE_COLUMNS = tuple(
    (eligible_id, direction)
    for eligible_id in ELIGIBLE_IDS
    for direction in PROFILE_DIRECTIONS
)
PROFILE_PARAMETER_COUNT = len(PROFILE_COLUMNS)
PROFILE_COLUMN_INDEX = {column: index for index, column in enumerate(PROFILE_COLUMNS)}

# Explicit numerical conventions.  These are frozen implementation constants;
# validation below prevents a config from claiming another policy.
NUMPY_MATRIX_RANK_ABSOLUTE_TOLERANCE = 1.0e-10
NNLS_MAX_ITERATIONS = 600
PROJECTOR_EQUALITY_TOLERANCE = 1.0e-7
PROJECTOR_SLACK_FIX_TOLERANCE = 1.0e-7
PROJECTOR_SLSQP_FTOL = 1.0e-9
PROJECTOR_MAX_ITERATIONS = 500
PROJECTOR_ROUNDING_REPAIR_MAX_PASSES = 800
PROJECTOR_SLSQP_DERIVATIVES = "analytic objective gradient and linear constraint Jacobians"
PROJECTION_DIRECTION_WEIGHTS = {"deposit": 1.0, "withdraw": 1.0}
PROJECTION_STATUS_VOCABULARY = (
    "optimal_exact",
    "optimal_minimum_slack",
    "stage2_fallback_exact",
    "stage2_fallback_minimum_slack",
    "incomplete_profile_only",
    "rate_only_prior",
    "rate_only_prior_balance_capped",
)


@dataclass(frozen=True)
class JsonSnapshot:
    """One no-follow, single-read JSON input bound to its exact bytes.

    The v2 runner treats configuration, calibration, and the confirmatory
    launch lock as execution inputs rather than decorative pathnames.  This
    immutable record is deliberately created from one descriptor read so a
    later pathname swap cannot combine an earlier checksum with later
    semantics.
    """

    path: Path
    label: str
    raw_bytes: bytes
    sha256: str
    payload: Mapping[str, Any]
    device: int
    inode: int
    size: int


@dataclass(frozen=True)
class ResolvedV2Config:
    """Typed, normalized configuration actually executed for one v2 run."""

    raw: Mapping[str, Any]
    normalized: Mapping[str, Any]
    executed_config_sha256: str
    activation_hazards: Mapping[str, float]
    solver_payload: Mapping[str, Any]
    solver_fingerprint: str
    calibration_file_sha256: str
    config_file_sha256: str
    calibration_payload: Mapping[str, Any]
    config_snapshot: JsonSnapshot | None
    calibration_snapshot: JsonSnapshot


def _snapshot_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    """Fields that detect a descriptor replacement or in-place mutation."""

    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)


def snapshot_json_file(path: str | Path, *, label: str) -> JsonSnapshot:
    """Read one JSON object once through an ``O_NOFOLLOW`` regular descriptor.

    The final pathname component must be an unlinked-by-others regular file
    (``st_nlink == 1``).  Device/inode/size/mtime are compared before and after
    the sole descriptor read.  A rename after opening is harmless because the
    captured descriptor remains the only source of both bytes and semantics;
    an in-place mutation is rejected instead of producing mixed provenance.
    """

    source = Path(path)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ValueError("v2 execution snapshots require os.O_NOFOLLOW support")
    try:
        listed = os.lstat(source)
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing: {source}") from error
    if stat.S_ISLNK(listed.st_mode):
        raise ValueError(f"{label} must not be a symlink: {source}")
    if not stat.S_ISREG(listed.st_mode):
        raise ValueError(f"{label} is not a regular file: {source}")
    if listed.st_nlink != 1:
        raise ValueError(f"{label} must have exactly one link: {source}")

    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(source, os.O_RDONLY | no_follow)
        except OSError as error:
            raise ValueError(f"{label} cannot be opened without following symlinks: {source}") from error
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"{label} is not a singly linked regular file: {source}")
        if (listed.st_dev, listed.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError(f"{label} changed before snapshot capture: {source}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _snapshot_identity(before) != _snapshot_identity(after) or after.st_nlink != 1:
            raise ValueError(f"{label} changed while snapshot bytes were read: {source}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    raw = b"".join(chunks)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {source}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object: {source}")
    return JsonSnapshot(
        path=source.resolve(), label=label, raw_bytes=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        payload=MappingProxyType(payload), device=before.st_dev,
        inode=before.st_ino, size=before.st_size,
    )


def canonical_json_sha256(payload: Any) -> str:
    """Hash a JSON-compatible object with an explicitly stable encoding."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect_equal(label: str, declared: Any, actual: Any) -> None:
    if declared != actual:
        raise ValueError(f"configured {label} does not exactly match frozen runtime value")


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"v2 config {key} must be an object")
    return value


def _int_list(payload: Mapping[str, Any], key: str) -> list[int]:
    value = payload.get(key)
    if not isinstance(value, list) or any(type(item) is not int for item in value):
        raise ValueError(f"v2 config {key} must be an integer array")
    return list(value)


def actual_solver_payload() -> dict[str, Any]:
    """Return solver provenance from executable code and loaded packages only."""

    import numpy
    import scipy

    return {
        "numpy_version": numpy.__version__,
        "scipy_version": scipy.__version__,
        "matrix_rank": {
            "library": "numpy.linalg.matrix_rank",
            "numpy_version": numpy.__version__,
            "absolute_tolerance": NUMPY_MATRIX_RANK_ABSOLUTE_TOLERANCE,
            "activation": "history_rank_before == 200",
            "condition_number": "numpy.linalg.cond(x, 2); infinity for empty/rank-deficient history",
        },
        "nnls": {
            "library": "scipy.optimize.nnls",
            "scipy_version": scipy.__version__,
            "max_iterations": NNLS_MAX_ITERATIONS,
        },
        "projector": {
            "stage1": "scipy.optimize.linprog(method=highs-ds), minimize s_plus+s_minus",
            "stage2": "scipy.optimize.minimize(method=SLSQP), weighted squared distance subject to minimum slack",
            "derivatives": PROJECTOR_SLSQP_DERIVATIVES,
            "scaling": "max(1, abs(public_delta_shares), max(predicted_shares), max(estimated_balance))",
            "equality_tolerance": PROJECTOR_EQUALITY_TOLERANCE,
            "slack_fix_tolerance": PROJECTOR_SLACK_FIX_TOLERANCE,
            "slsqp_ftol": PROJECTOR_SLSQP_FTOL,
            "max_iterations": PROJECTOR_MAX_ITERATIONS,
            "rounding_repair_max_passes": PROJECTOR_ROUNDING_REPAIR_MAX_PASSES,
            "direction_weights": dict(PROJECTION_DIRECTION_WEIGHTS),
            "status_vocabulary": list(PROJECTION_STATUS_VOCABULARY),
        },
    }


def _runtime_declarations() -> dict[str, Any]:
    """All JSON-declared values that are implemented as code constants."""

    return {
        "population_size": POPULATION_SIZE,
        "days": DAYS,
        "horizons": list(HORIZONS),
        "k_values": list(K_VALUES),
        "releases": list(RELEASES),
        "traffic_modes": list(TRAFFIC_MODES),
        "development_seed_range": [DEVELOPMENT_SEEDS[0], DEVELOPMENT_SEEDS[-1]],
        "confirmatory_seed_range_reserved": [CONFIRMATORY_SEEDS[0], CONFIRMATORY_SEEDS[-1]],
        "moving_block": {
            "block_days": MOVING_BLOCK_DAYS,
            "boundary": MOVING_BLOCK_BOUNDARY,
            "truncate_days": DAYS,
        },
        "uniform_time": {
            "representation": UNIFORM_TIME_REPRESENTATION,
            "tie_break": UNIFORM_TIME_TIE_BREAK,
        },
        "profile_bootstrap": {
            "independent_components": ["recurrence", "deposit", "withdraw"],
            "share_unit": "microshares_per_operation",
            "shrinkage_formula": "alpha=n/(n+5); log_profile=alpha*address_log_median+(1-alpha)*global_log_median",
            "missing_direction": "direction_global_log_median",
            "residual_clip_abs_log": DEFAULT_RESIDUAL_LOG_CLIP,
        },
        "action_generation": {
            "raw_direction_source": "filtered empirical D/W count ratio",
            "unfunded_withdrawal": "reselect funded identifier; convert to deposit only if none funded",
            "full_withdraw_probability": FULL_WITHDRAW_PROBABILITY,
            "full_withdraw_comparator": "uniform_draw < probability",
        },
        "rate_process": {
            "source": "v1 audited Yearn-quantile generator",
            "same_day_fixed_rate": True,
        },
        "attacker": {
            "fixed_profile_domain": {
                "public_enrollment_roster": "u000..u099",
                "column_order": "eligible_id ascending, then deposit, withdraw",
                "parameter_column_count": PROFILE_PARAMETER_COUNT,
                "unseen_pair_policy": "retain as zero column; never dynamically remove",
            },
            **actual_solver_payload(),
        },
    }


def _normalized_payload(config: Mapping[str, Any], activation_hazards: Mapping[str, float], calibration_sha: str) -> dict[str, Any]:
    """Build the typed semantic payload recorded with every executed shard."""

    runtime = _runtime_declarations()
    return {
        "schema_version": str(config["schema_version"]),
        "evidence_status": str(config["evidence_status"]),
        "constant_status": str(config["constant_status"]),
        "constant_status_vocabulary": [str(item) for item in config["constant_status_vocabulary"]],
        "population_size": int(runtime["population_size"]),
        "days": int(runtime["days"]),
        "horizons": [int(item) for item in runtime["horizons"]],
        "k_values": [int(item) for item in runtime["k_values"]],
        "releases": [str(item) for item in runtime["releases"]],
        "traffic_modes": [str(item) for item in runtime["traffic_modes"]],
        "development_seed_range": [int(item) for item in runtime["development_seed_range"]],
        "confirmatory_seed_range_reserved": [int(item) for item in runtime["confirmatory_seed_range_reserved"]],
        "moving_block": {**runtime["moving_block"], "status": str(_mapping(config, "moving_block")["status"])},
        "uniform_time": {**runtime["uniform_time"], "status": str(_mapping(config, "uniform_time")["status"])},
        "profile_bootstrap": {**runtime["profile_bootstrap"], "status": str(_mapping(config, "profile_bootstrap")["status"])},
        "activation": {
            "target_mean_distinct_identifiers_day365": int(_mapping(config, "activation")["target_mean_distinct_identifiers_day365"]),
            "hazard_function": str(_mapping(config, "activation")["hazard_function"]),
            "hazards": {mode: float(activation_hazards[mode]) for mode in TRAFFIC_MODES},
            "no_forced_activation": bool(_mapping(config, "activation")["no_forced_activation"]),
            "calibration": {
                key: value
                for key, value in dict(_mapping(_mapping(config, "activation"), "calibration")).items()
                if key != "executed_config_sha256"
            },
            "status": str(_mapping(config, "activation")["status"]),
        },
        "action_generation": {**runtime["action_generation"], "status": str(_mapping(config, "action_generation")["status"])},
        "rate_process": {**runtime["rate_process"], "status": str(_mapping(config, "rate_process")["status"])},
        "attacker": {**runtime["attacker"], "status": str(_mapping(config, "attacker")["status"])},
        "calibration_artifact": str(config["calibration_artifact"]),
        "calibration_artifact_sha256": calibration_sha,
    }


def validate_execution_config(
    config: Mapping[str, Any] | JsonSnapshot,
    *,
    calibration_path: str | Path | None = None,
    calibration_snapshot: JsonSnapshot | None = None,
    config_snapshot: JsonSnapshot | None = None,
) -> ResolvedV2Config:
    """Fail closed unless JSON declarations match the executed v2 contract.

    Activation hazards are intentionally the sole declared environment setting
    read as runtime authority.  All other declared numerical/scientific values
    match their frozen implementations exactly, preventing misleading config
    provenance when source and config drift apart.
    """

    if isinstance(config, JsonSnapshot):
        if config_snapshot is not None and config_snapshot != config:
            raise ValueError("v2 config snapshot disagreement")
        config_snapshot = config
        config = config.payload
    if config_snapshot is not None and dict(config) != dict(config_snapshot.payload):
        raise ValueError("v2 config mapping does not match its captured snapshot")
    if calibration_snapshot is None:
        if calibration_path is None:
            raise ValueError("v2 execution config validation requires a calibration snapshot or path")
        calibration_snapshot = snapshot_json_file(calibration_path, label="v2 calibration input")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("v2 config schema version mismatch")
    for key, expected in (("k_values", list(K_VALUES)), ("horizons", list(HORIZONS)),
                          ("releases", list(RELEASES)), ("traffic_modes", list(TRAFFIC_MODES)),
                          ("development_seed_range", [DEVELOPMENT_SEEDS[0], DEVELOPMENT_SEEDS[-1]]),
                          ("confirmatory_seed_range_reserved", [CONFIRMATORY_SEEDS[0], CONFIRMATORY_SEEDS[-1]])):
        _expect_equal(key, _int_list(config, key) if key in {"k_values", "horizons", "development_seed_range", "confirmatory_seed_range_reserved"} else config.get(key), expected)
    _expect_equal("population_size", config.get("population_size"), POPULATION_SIZE)
    _expect_equal("days", config.get("days"), DAYS)
    statuses = config.get("constant_status_vocabulary")
    if not isinstance(statuses, list) or str(config.get("constant_status")) not in statuses:
        raise ValueError("v2 config has invalid constant status vocabulary")

    runtime = _runtime_declarations()
    for section in ("moving_block", "uniform_time", "profile_bootstrap", "action_generation", "rate_process"):
        declared = _mapping(config, section)
        for key, expected in runtime[section].items():
            _expect_equal(f"{section}.{key}", declared.get(key), expected)
    activation = _mapping(config, "activation")
    _expect_equal("activation.target_mean_distinct_identifiers_day365", activation.get("target_mean_distinct_identifiers_day365"), 95)
    _expect_equal("activation.hazard_function", activation.get("hazard_function"), ACTIVATION_HAZARD_FUNCTION)
    _expect_equal("activation.no_forced_activation", activation.get("no_forced_activation"), True)
    activation_calibration = _mapping(activation, "calibration")
    if not activation_calibration.get("algorithm"):
        raise ValueError("activation calibration must declare its fitting algorithm")
    declared_hazards = _mapping(activation, "hazards")
    if set(declared_hazards) != set(TRAFFIC_MODES):
        raise ValueError("configured activation hazards must cover exactly the frozen traffic modes")
    hazards: dict[str, float] = {}
    for mode in TRAFFIC_MODES:
        value = declared_hazards[mode]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"configured activation hazard for {mode} must be a finite probability")
        hazards[mode] = float(value)

    attacker = _mapping(config, "attacker")
    for section in ("fixed_profile_domain", "matrix_rank", "nnls", "projector"):
        _expect_equal(f"attacker.{section}", attacker.get(section), runtime["attacker"][section])

    calibration_sha = calibration_snapshot.sha256
    _expect_equal("calibration_artifact_sha256", config.get("calibration_artifact_sha256"), calibration_sha)
    calibration = calibration_snapshot.payload
    pools = calibration.get("profile_pools", {})
    for direction in ("deposit", "withdraw"):
        pool = pools.get(direction, {})
        _expect_equal(f"calibration.{direction}.shrinkage.formula", pool.get("shrinkage", {}).get("formula"), runtime["profile_bootstrap"]["shrinkage_formula"])
        _expect_equal(f"calibration.{direction}.shrinkage.addend", pool.get("shrinkage", {}).get("addend"), DEFAULT_SHRINKAGE_ADDEND)
        _expect_equal(f"calibration.{direction}.residual.clip_abs", pool.get("residual_transform", {}).get("clip_abs"), DEFAULT_RESIDUAL_LOG_CLIP)
        _expect_equal(f"calibration.{direction}.unit", pool.get("unit"), runtime["profile_bootstrap"]["share_unit"])
    _expect_equal("calibration.full_exit_audit.frozen_probability", calibration.get("full_exit_audit", {}).get("frozen_probability"), FULL_WITHDRAW_PROBABILITY)

    solver_payload = actual_solver_payload()
    normalized = _normalized_payload(config, hazards, calibration_sha)
    executed_config_sha256 = canonical_json_sha256(normalized)
    declared_executed_hash = activation_calibration.get("executed_config_sha256")
    if declared_executed_hash is not None and declared_executed_hash != executed_config_sha256:
        raise ValueError("activation calibration executed-config hash does not match runtime payload")
    return ResolvedV2Config(
        raw=dict(config), normalized=normalized,
        executed_config_sha256=executed_config_sha256,
        activation_hazards=MappingProxyType(hazards), solver_payload=MappingProxyType(solver_payload),
        solver_fingerprint=canonical_json_sha256(solver_payload),
        calibration_file_sha256=calibration_sha,
        config_file_sha256=config_snapshot.sha256 if config_snapshot is not None else canonical_json_sha256(config),
        calibration_payload=calibration,
        config_snapshot=config_snapshot,
        calibration_snapshot=calibration_snapshot,
    )


def load_development_config(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate a non-evidence v2 development config."""

    config = dict(snapshot_json_file(path, label="v2 development config").payload)
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unexpected v2 schema version")
    if config.get("evidence_status") != "development":
        raise ValueError("v2 development config must not be marked confirmatory")
    return config
