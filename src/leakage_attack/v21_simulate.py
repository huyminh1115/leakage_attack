"""Fresh development trace orchestration for the minimal v2.1 public heuristic.

Private synthetic generation reuses the frozen v2 modules unchanged.  The
public estimator sees only the transcript emitted by disclosure; truth is joined
later by :mod:`leakage_attack.v21_evaluate`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .v21_config import (
    DAYS, DEVELOPMENT_SEEDS, EXPERIMENT_ROOT, HORIZONS, K_VALUES, RELEASE,
    SCHEMA_VERSION as CONFIG_SCHEMA_VERSION, ResolvedV21Config, TRAFFIC_MODES,
    canonical_json_sha256, file_sha256,
)
from .v21_estimator import V21EstimatorError, estimate
from .v21_evaluate import evaluate, operation_metrics_row, position_metrics_row
from .v2_disclosure import build_transcript, checkpoint_schedule, partition_strict_k
from .v2_simulator import LatentTrace, simulate_latent_trace

METRIC_COLUMNS = (
    "schema_version", "phase", "traffic_mode", "seed", "k", "release", "horizon_day",
    "latent_trace_hash", "action_trace_hash", "checkpoint_schedule_hash",
    "config_sha256", "semantic_config_sha256", "calibration_sha256", "source_code_fingerprint",
    "reused_v2_modules_sha256", "dependency_lock_sha256", "solver_fingerprint",
    "solver_status", "solver_message", "solver_runtime_seconds",
    "public_action_count", "completed_checkpoint_count", "modeled_action_count", "tail_action_count",
    "active_eligible_participants", "position_within_10pct",
    "completed_operation_count", "completed_operation_within_10pct",
    "tail_operation_count", "tail_operation_within_10pct", "all_operation_count", "all_operation_within_10pct",
)

SOLVER_DIAGNOSTIC_COLUMNS = (
    "schema_version", "phase", "traffic_mode", "seed", "k", "release", "horizon_day",
    "latent_trace_hash", "action_trace_hash", "checkpoint_schedule_hash",
    "config_sha256", "semantic_config_sha256", "calibration_sha256", "source_code_fingerprint",
    "reused_v2_modules_sha256", "dependency_lock_sha256", "solver_fingerprint",
    "solver_status", "solver_message", "solver_runtime_seconds", "modeled_action_count",
    "completed_checkpoint_count", "tail_action_count", "scale_m", "objective",
    "max_checkpoint_residual_normalized", "min_balance_normalized", "linprog_status",
    "slsqp_status", "slsqp_iterations",
)

PUBLIC_ACTION_ESTIMATE_COLUMNS = (
    "schema_version", "phase", "traffic_mode", "seed", "k", "release", "horizon_day",
    "action_id", "eligible_id", "action_type", "day", "within_day_tick", "global_order",
    "inferred_shares", "completed", "tail_abstention", "estimated_balance_before", "estimated_balance_after",
)

PRIVATE_TRUTH_JOIN_COLUMNS = (
    "schema_version", "phase", "traffic_mode", "seed", "k", "release", "horizon_day",
    "action_id", "truth_shares", "truth_assets", "truth_position_before", "truth_position_after", "truth_full_withdraw",
    "inferred_shares", "completed", "tail_abstention",
)

TRAFFIC_DIAGNOSTIC_COLUMNS = (
    "schema_version", "phase", "traffic_mode", "seed", "latent_trace_hash", "action_trace_hash",
    "config_sha256", "semantic_config_sha256", "calibration_sha256", "source_code_fingerprint",
    "reused_v2_modules_sha256", "dependency_lock_sha256", "solver_fingerprint",
    "daily_event_count", "realized_distinct_identifiers", "realized_deposit_count", "realized_withdraw_count",
)

SCHEMA_VERSION = CONFIG_SCHEMA_VERSION
PHASE = "development"
_REUSED_V2_MODULES = ("v2_calibration.py", "v2_config.py", "v2_disclosure.py", "v2_simulator.py")


@dataclass(frozen=True)
class V21SeedArtifacts:
    """Public and private rows generated for exactly one development seed."""

    metrics: list[dict[str, Any]]
    solver_diagnostics: list[dict[str, Any]]
    public_action_estimates: list[dict[str, Any]]
    private_truth_joins: list[dict[str, Any]]
    traffic_diagnostics: list[dict[str, Any]]
    provenance: Mapping[str, str]
    source_manifest: Mapping[str, Any]


def _canonical_hash(value: Any) -> str:
    return canonical_json_sha256(value)


def _public_actions(trace: LatentTrace) -> list[dict[str, Any]]:
    return [
        {key: event[key] for key in ("action_id", "day", "within_day_tick", "global_order", "eligible_id", "action_type")}
        for event in trace.events
    ]


def _trace_hashes(trace: LatentTrace) -> tuple[str, str]:
    latent = {
        "seed": trace.seed, "traffic_mode": trace.traffic_mode, "rates": trace.rates,
        "daily_counts": trace.daily_counts, "profiles": {name: asdict(value) for name, value in trace.profiles.items()},
        "events": trace.events, "final_positions": trace.final_positions, "diagnostics": trace.diagnostics,
    }
    return _canonical_hash(latent), _canonical_hash(_public_actions(trace))


def source_fingerprint() -> tuple[dict[str, Any], str, str]:
    """Hash v2.1 code separately from unchanged v2 implementation dependencies."""

    source_root = EXPERIMENT_ROOT / "src" / "leakage_attack"
    v21_files = sorted(source_root.glob("v21_*.py"))
    if not v21_files:
        raise RuntimeError("v2.1 source fingerprint found no v21 modules")
    v21_entries: list[dict[str, str]] = []
    digest = hashlib.sha256()
    for path in v21_files:
        content = path.read_bytes()
        relative = path.relative_to(EXPERIMENT_ROOT).as_posix()
        v21_entries.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
        digest.update(relative.encode("utf-8")); digest.update(b"\0"); digest.update(content); digest.update(b"\0")
    reused_entries: list[dict[str, str]] = []
    for name in _REUSED_V2_MODULES:
        path = source_root / name
        content = path.read_bytes()
        reused_entries.append({"path": path.relative_to(EXPERIMENT_ROOT).as_posix(), "sha256": hashlib.sha256(content).hexdigest()})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_scope": "v21_python_only",
        "v21_files": v21_entries,
        "reused_unchanged_v2_modules": reused_entries,
    }
    return manifest, digest.hexdigest(), _canonical_hash(reused_entries)


def _provenance(resolved: ResolvedV21Config) -> tuple[dict[str, str], dict[str, Any]]:
    manifest, source_hash, reused_hash = source_fingerprint()
    lock = EXPERIMENT_ROOT / "requirements-v2.lock"
    solver_hash = _canonical_hash(dict(resolved.solver_payload))
    return {
        "config_sha256": resolved.config_snapshot.sha256,
        "semantic_config_sha256": resolved.semantic_config_sha256,
        "calibration_sha256": resolved.calibration_snapshot.sha256,
        "source_code_fingerprint": source_hash,
        "reused_v2_modules_sha256": reused_hash,
        "dependency_lock_sha256": file_sha256(lock),
        "solver_fingerprint": solver_hash,
    }, manifest


def _truth_prefix(events: Sequence[Mapping[str, Any]], horizon: int) -> list[dict[str, Any]]:
    return [dict(event) for event in events if int(event["day"]) < horizon]


def _cell_common(
    *, seed: int, traffic_mode: str, k: int, horizon: int, latent_hash: str, action_hash: str,
    schedule_hash: str, provenance: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "phase": PHASE, "traffic_mode": traffic_mode,
        "seed": seed, "k": k, "release": RELEASE, "horizon_day": horizon,
        "latent_trace_hash": latent_hash, "action_trace_hash": action_hash,
        "checkpoint_schedule_hash": schedule_hash, **provenance,
    }


def _failed_rows(common: Mapping[str, Any], *, error: V21EstimatorError, elapsed: float, public_action_count: int, checkpoint_count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    message = str(error)
    metric = {
        **common, "solver_status": "failed", "solver_message": message, "solver_runtime_seconds": elapsed,
        "public_action_count": public_action_count, "completed_checkpoint_count": checkpoint_count,
        "modeled_action_count": "", "tail_action_count": "", "active_eligible_participants": "",
        "position_within_10pct": "", "completed_operation_count": "", "completed_operation_within_10pct": "",
        "tail_operation_count": "", "tail_operation_within_10pct": "", "all_operation_count": "",
        "all_operation_within_10pct": "",
    }
    diagnostic = {
        **common, "solver_status": "failed", "solver_message": message, "solver_runtime_seconds": elapsed,
        "modeled_action_count": "", "completed_checkpoint_count": checkpoint_count, "tail_action_count": "",
        "scale_m": "", "objective": "", "max_checkpoint_residual_normalized": "",
        "min_balance_normalized": "", "linprog_status": "", "slsqp_status": "", "slsqp_iterations": "",
    }
    return metric, diagnostic


def _rows_from_success(
    common: Mapping[str, Any], result: Any, truth: Sequence[Mapping[str, Any]], elapsed: float,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Join truth only after the public result has been fully constructed."""

    evaluation = evaluate(truth, result)
    diagnostic = result.diagnostic
    metric = {
        **common, "solver_status": diagnostic.status, "solver_message": diagnostic.message,
        "solver_runtime_seconds": elapsed, "public_action_count": len(result.action_estimates),
        "completed_checkpoint_count": result.completed_checkpoint_count,
        "modeled_action_count": diagnostic.modeled_action_count, "tail_action_count": diagnostic.tail_action_count,
        **position_metrics_row(evaluation.position), **operation_metrics_row(evaluation.operation),
    }
    solver_row = {
        **common, "solver_status": diagnostic.status, "solver_message": diagnostic.message,
        "solver_runtime_seconds": elapsed, "modeled_action_count": diagnostic.modeled_action_count,
        "completed_checkpoint_count": diagnostic.completed_checkpoint_count,
        "tail_action_count": diagnostic.tail_action_count, "scale_m": diagnostic.scale_m,
        "objective": diagnostic.objective,
        "max_checkpoint_residual_normalized": diagnostic.max_checkpoint_residual_normalized,
        "min_balance_normalized": diagnostic.min_balance_normalized, "linprog_status": diagnostic.linprog_status,
        "slsqp_status": diagnostic.slsqp_status, "slsqp_iterations": diagnostic.slsqp_iterations,
    }
    public_rows = []
    truth_by_id = {str(event["action_id"]): event for event in truth}
    private_rows = []
    for action in result.action_estimates:
        public_rows.append({
            **{name: common[name] for name in ("schema_version", "phase", "traffic_mode", "seed", "k", "release", "horizon_day")},
            "action_id": action.action_id, "eligible_id": action.eligible_id, "action_type": action.action_type,
            "day": action.day, "within_day_tick": action.within_day_tick, "global_order": action.global_order,
            "inferred_shares": action.inferred_shares, "completed": action.completed,
            "tail_abstention": action.tail_abstention, "estimated_balance_before": action.estimated_balance_before,
            "estimated_balance_after": action.estimated_balance_after,
        })
        event = truth_by_id.get(action.action_id)
        if event is None:
            raise AssertionError("sealed public estimate has no private horizon event")
        private_rows.append({
            **{name: common[name] for name in ("schema_version", "phase", "traffic_mode", "seed", "k", "release", "horizon_day")},
            "action_id": action.action_id, "truth_shares": int(event["shares"]), "truth_assets": int(event["assets"]),
            "truth_position_before": int(event["position_before"]), "truth_position_after": int(event["position_after"]),
            "truth_full_withdraw": bool(event["full_withdraw"]), "inferred_shares": action.inferred_shares,
            "completed": action.completed, "tail_abstention": action.tail_abstention,
        })
    return metric, solver_row, public_rows, private_rows


def _traffic_row(trace: LatentTrace, *, seed: int, traffic_mode: str, latent_hash: str, action_hash: str, provenance: Mapping[str, str]) -> dict[str, Any]:
    events = trace.events
    return {
        "schema_version": SCHEMA_VERSION, "phase": PHASE, "traffic_mode": traffic_mode, "seed": seed,
        "latent_trace_hash": latent_hash, "action_trace_hash": action_hash, **provenance,
        "daily_event_count": len(events), "realized_distinct_identifiers": trace.distinct_observed,
        "realized_deposit_count": sum(event["action_type"] == "deposit" for event in events),
        "realized_withdraw_count": sum(event["action_type"] == "withdraw" for event in events),
    }


def run_seed_artifacts(seed: int, *, resolved: ResolvedV21Config) -> V21SeedArtifacts:
    """Generate exactly 120 v2.1 cells from one paired seed across both traffic modes."""

    if type(seed) is not int or seed not in DEVELOPMENT_SEEDS:
        raise ValueError("v2.1 development seed is outside 41001..41030")
    calibration = dict(resolved.calibration_snapshot.payload)
    provenance, source_manifest = _provenance(resolved)
    metrics: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    public_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    traffic_rows: list[dict[str, Any]] = []
    for traffic_mode in TRAFFIC_MODES:
        trace = simulate_latent_trace(
            calibration, seed=seed, days=DAYS, traffic_mode=traffic_mode,
            activation_hazards=resolved.activation_hazards,
        )
        latent_hash, action_hash = _trace_hashes(trace)
        traffic_rows.append(_traffic_row(
            trace, seed=seed, traffic_mode=traffic_mode, latent_hash=latent_hash, action_hash=action_hash,
            provenance=provenance,
        ))
        for k in K_VALUES:
            partition = partition_strict_k(trace.events, days=DAYS, k=k)
            if any(window.participant_count != k for window in partition.completed):
                raise AssertionError("strict-k partition failed immediate participant threshold")
            schedule_hash = _canonical_hash(checkpoint_schedule(partition))
            transcript = build_transcript(trace.events, days=DAYS, partition=partition, release=RELEASE)
            if any(record.get("release") != RELEASE for record in transcript if record["record_type"] == "checkpoint"):
                raise AssertionError("v2.1 emitted a non-checkpoint-total transcript")
            for horizon in HORIZONS:
                common = _cell_common(
                    seed=seed, traffic_mode=traffic_mode, k=k, horizon=horizon,
                    latent_hash=latent_hash, action_hash=action_hash, schedule_hash=schedule_hash, provenance=provenance,
                )
                started = time.perf_counter()
                try:
                    sealed = estimate(transcript, horizon=horizon)
                    elapsed = time.perf_counter() - started
                    truth = _truth_prefix(trace.events, horizon)
                    metric, solver_row, per_action_public, per_action_private = _rows_from_success(common, sealed, truth, elapsed)
                    metrics.append(metric); diagnostics.append(solver_row)
                    public_rows.extend(per_action_public); private_rows.extend(per_action_private)
                except V21EstimatorError as error:
                    elapsed = time.perf_counter() - started
                    public_count = sum(record["record_type"] == "action" and int(record["day"]) < horizon for record in transcript)
                    checkpoint_count = sum(record["record_type"] == "checkpoint" and int(record["day"]) < horizon for record in transcript)
                    metric, solver_row = _failed_rows(
                        common, error=error, elapsed=elapsed, public_action_count=public_count,
                        checkpoint_count=checkpoint_count,
                    )
                    metrics.append(metric); diagnostics.append(solver_row)
    expected = len(TRAFFIC_MODES) * len(K_VALUES) * len(HORIZONS)
    if len(metrics) != expected or len(diagnostics) != expected:
        raise AssertionError(f"v2.1 seed matrix has {len(metrics)} cells, expected {expected}")
    for rows, columns in ((metrics, METRIC_COLUMNS), (diagnostics, SOLVER_DIAGNOSTIC_COLUMNS), (public_rows, PUBLIC_ACTION_ESTIMATE_COLUMNS), (private_rows, PRIVATE_TRUTH_JOIN_COLUMNS), (traffic_rows, TRAFFIC_DIAGNOSTIC_COLUMNS)):
        if any(tuple(row) != tuple(columns) for row in rows):
            raise AssertionError("v2.1 artifact row does not match its frozen schema")
    return V21SeedArtifacts(metrics, diagnostics, public_rows, private_rows, traffic_rows, provenance, source_manifest)


__all__ = [
    "METRIC_COLUMNS", "PRIVATE_TRUTH_JOIN_COLUMNS", "PUBLIC_ACTION_ESTIMATE_COLUMNS", "SCHEMA_VERSION",
    "SOLVER_DIAGNOSTIC_COLUMNS", "TRAFFIC_DIAGNOSTIC_COLUMNS", "V21SeedArtifacts", "run_seed_artifacts",
    "source_fingerprint",
]
