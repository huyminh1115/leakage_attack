"""Deterministic public-prefix minimum-norm checkpoint reconstruction.

The public seam is intentionally small: :func:`estimate` receives transcript
records and a horizon.  It uses only action metadata and cumulative share
totals.  All other study components must keep generator calibration and hidden
outcomes on the other side of that seam.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import linprog, minimize

from .v21_config import HIGHS_PRESOLVE, NORMALIZED_CONSTRAINT_TOLERANCE, SLSQP_FTOL, SLSQP_MAXITER

ELIGIBLE_IDS = tuple(f"u{index:03d}" for index in range(100))
_ACTION_FIELDS = {
    "record_type", "action_id", "eligible_id", "action_type", "day", "within_day_tick", "global_order",
}
_CHECKPOINT_REQUIRED_FIELDS = {
    "record_type", "checkpoint_id", "release", "day", "within_day_tick", "global_order", "checkpoint_shares",
}
_CHECKPOINT_ALLOWED_FIELDS = _CHECKPOINT_REQUIRED_FIELDS | {"rate", "checkpoint_assets"}
_FORBIDDEN_FIELDS = {
    "shares", "assets", "position_before", "position_after", "full_withdraw", "pro" + "file_log_shares",
    "residual_log", "aggregate_shares_after", "aggregate_assets_after", "activation_event",
    "withdrawal_reselected", "withdrawal_converted", "final_positions", "latent_trace_hash",
}


class V21EstimatorError(ValueError):
    """A malformed or numerically unresolved public prefix fails closed."""


@dataclass(frozen=True)
class V21ActionEstimate:
    """One public action's continuous reconstruction or explicit zero tail abstention."""

    action_id: str
    eligible_id: str
    action_type: str
    day: int
    within_day_tick: int
    global_order: int
    inferred_shares: float
    completed: bool
    tail_abstention: bool
    estimated_balance_before: float
    estimated_balance_after: float


@dataclass(frozen=True)
class V21SolveDiagnostic:
    """Numerical facts checked after the two public optimization stages."""

    status: str
    message: str
    modeled_action_count: int
    completed_checkpoint_count: int
    tail_action_count: int
    scale_m: float
    objective: float
    max_checkpoint_residual_normalized: float
    min_balance_normalized: float
    linprog_status: int
    slsqp_status: int
    slsqp_iterations: int


@dataclass(frozen=True)
class V21EstimateResult:
    """Immutable output of the public estimator for one causal horizon prefix."""

    final_positions: Mapping[str, float]
    action_estimates: tuple[V21ActionEstimate, ...]
    completed_checkpoint_count: int
    diagnostic: V21SolveDiagnostic


def _integer(value: Any, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise V21EstimatorError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise V21EstimatorError(f"{label} must be at least {minimum}")
    return value


def _reject_hidden_fields(record: Mapping[str, Any]) -> None:
    if any(key in _FORBIDDEN_FIELDS or str(key).startswith("truth_") for key in record):
        raise V21EstimatorError("public transcript includes a hidden field")


def _record_key(record: Mapping[str, Any], type_order: int) -> tuple[int, int, int, int]:
    return (
        _integer(record.get("day"), "record day", minimum=0),
        _integer(record.get("within_day_tick"), "record within_day_tick", minimum=0),
        _integer(record.get("global_order"), "record global_order", minimum=0),
        type_order,
    )


def _visible_records(public_transcript: Sequence[Mapping[str, Any]], horizon: int) -> list[dict[str, Any]]:
    """Select the causal day prefix before inspecting non-day record fields.

    Every record needs a valid day to establish whether it is visible.  Once a
    record is strictly after the horizon, its type, ordering, and payload are
    outside the causal input and are deliberately not inspected.
    """

    if type(horizon) is not int or horizon <= 0:
        raise V21EstimatorError("horizon must be a positive integer day count")
    if not isinstance(public_transcript, Sequence) or isinstance(public_transcript, (str, bytes)):
        raise V21EstimatorError("public transcript must be a sequence of records")
    visible: list[dict[str, Any]] = []
    for raw in public_transcript:
        if not isinstance(raw, Mapping):
            raise V21EstimatorError("public transcript record must be a mapping")
        day = _integer(raw.get("day"), "record day", minimum=0)
        if day < horizon:
            visible.append(dict(raw))
    return visible


def _validated_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Strictly validate the already selected visible public prefix."""

    validated: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    seen_action_orders: set[tuple[int, int, int]] = set()
    seen_checkpoints: set[int] = set()
    previous: tuple[int, int, int, int] | None = None
    previous_checkpoint_id = -1
    actions_since_checkpoint = 0
    for raw in records:
        if not isinstance(raw, Mapping):
            raise V21EstimatorError("public transcript record must be a mapping")
        record = dict(raw)
        _reject_hidden_fields(record)
        record_type = record.get("record_type")
        if record_type == "action":
            if set(record) != _ACTION_FIELDS:
                raise V21EstimatorError("public action fields do not match the v2.1 allowlist")
            action_id = record.get("action_id")
            if not isinstance(action_id, str) or not action_id or action_id in seen_actions:
                raise V21EstimatorError("public action IDs must be unique nonempty strings")
            seen_actions.add(action_id)
            eligible_id = record.get("eligible_id")
            if eligible_id not in ELIGIBLE_IDS:
                raise V21EstimatorError("public action eligible identifier is outside the fixed roster")
            if record.get("action_type") not in {"deposit", "withdraw"}:
                raise V21EstimatorError("public action type is invalid")
            key = _record_key(record, 0)
            action_order = key[:3]
            if action_order in seen_action_orders:
                raise V21EstimatorError("public action order must be unique")
            seen_action_orders.add(action_order)
            actions_since_checkpoint += 1
        elif record_type == "checkpoint":
            if not _CHECKPOINT_REQUIRED_FIELDS <= set(record) or not set(record) <= _CHECKPOINT_ALLOWED_FIELDS:
                raise V21EstimatorError("public checkpoint fields do not match the v2.1 allowlist")
            if record.get("release") != "checkpoint_totals":
                raise V21EstimatorError("public checkpoint release is unsupported")
            checkpoint_id = _integer(record.get("checkpoint_id"), "checkpoint ID", minimum=0)
            if checkpoint_id in seen_checkpoints or checkpoint_id <= previous_checkpoint_id:
                raise V21EstimatorError("public checkpoint IDs must be unique and increasing")
            seen_checkpoints.add(checkpoint_id)
            previous_checkpoint_id = checkpoint_id
            _integer(record.get("checkpoint_shares"), "checkpoint shares", minimum=0)
            key = _record_key(record, 1)
            if actions_since_checkpoint <= 0 or previous != (key[0], key[1], key[2], 0):
                raise V21EstimatorError("public checkpoint must directly follow a new public action")
            actions_since_checkpoint = 0
        else:
            raise V21EstimatorError("public record type is invalid")
        if previous is not None and key < previous:
            raise V21EstimatorError("public transcript ordering is unstable")
        previous = key
        validated.append(record)
    return validated


def _causal_prefix(visible: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return actions, modeled actions, and completed checkpoints from the visible prefix."""

    last_checkpoint_index: int | None = None
    for index, record in enumerate(visible):
        if record["record_type"] == "checkpoint":
            last_checkpoint_index = index
    visible_actions = [record for record in visible if record["record_type"] == "action"]
    if last_checkpoint_index is None:
        return visible_actions, [], []
    modeled = [record for record in visible[:last_checkpoint_index] if record["record_type"] == "action"]
    checkpoints = [record for record in visible[:last_checkpoint_index + 1] if record["record_type"] == "checkpoint"]
    if not modeled or not checkpoints:
        raise V21EstimatorError("completed public checkpoint prefix is empty")
    return visible_actions, modeled, checkpoints


def _finite_solver_float(value: int, label: str) -> float:
    """Convert one validated public integer into a finite solver input."""

    try:
        converted = float(value)
    except (OverflowError, ValueError, TypeError) as error:
        raise V21EstimatorError(f"{label} cannot be represented as a finite solver float") from error
    if not math.isfinite(converted):
        raise V21EstimatorError(f"{label} cannot be represented as a finite solver float")
    return converted


def _constraint_matrices(
    modeled_actions: Sequence[Mapping[str, Any]], checkpoints: Sequence[Mapping[str, Any]], scale_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build scaled cumulative-total and per-user balance constraints."""

    count = len(modeled_actions)
    signs = np.asarray([1.0 if action["action_type"] == "deposit" else -1.0 for action in modeled_actions])
    cumulative_rows: list[np.ndarray] = []
    cumulative_totals: list[float] = []
    # The estimator caller gives separate lists, so derive each endpoint from
    # checkpoint global orders.  A checkpoint is emitted directly after its
    # final action and shares that action's order in the reused disclosure.
    endpoints: list[int] = []
    previous_endpoint = 0
    for checkpoint in checkpoints:
        endpoint = sum(
            1 for action in modeled_actions
            if (int(action["day"]), int(action["within_day_tick"]), int(action["global_order"]))
            <= (int(checkpoint["day"]), int(checkpoint["within_day_tick"]), int(checkpoint["global_order"]))
        )
        if endpoint <= previous_endpoint:
            raise V21EstimatorError("checkpoint has no public actions since the previous checkpoint")
        endpoints.append(endpoint)
        previous_endpoint = endpoint
    if endpoints[-1] != count:
        raise V21EstimatorError("modeled action prefix does not end at the final completed checkpoint")
    for endpoint, checkpoint in zip(endpoints, checkpoints):
        row = np.zeros(count, dtype=float)
        row[:endpoint] = signs[:endpoint]
        cumulative_rows.append(row)
        cumulative_totals.append(_finite_solver_float(
            int(checkpoint["checkpoint_shares"]), "checkpoint shares",
        ) / scale_m)
    equality = np.vstack(cumulative_rows)
    response = np.asarray(cumulative_totals, dtype=float)
    balance = np.zeros((count, count), dtype=float)
    users: dict[str, list[int]] = {}
    for index, action in enumerate(modeled_actions):
        users.setdefault(str(action["eligible_id"]), []).append(index)
        for earlier_index in users[str(action["eligible_id"])]:
            balance[index, earlier_index] = signs[earlier_index]
    if not np.all(np.isfinite(equality)) or not np.all(np.isfinite(response)) or not np.all(np.isfinite(balance)):
        raise V21EstimatorError("public constraint matrix is not finite")
    return equality, response, balance


def _solve(modeled_actions: Sequence[Mapping[str, Any]], checkpoints: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, V21SolveDiagnostic]:
    """Find a feasible point then its unique equal-weight minimum-norm tie-break."""

    totals = [abs(int(checkpoint["checkpoint_shares"])) for checkpoint in checkpoints]
    scale_m = _finite_solver_float(max([1, *totals]), "checkpoint share scale")
    equality, response, balance = _constraint_matrices(modeled_actions, checkpoints, scale_m)
    count = len(modeled_actions)
    feasible = linprog(
        c=np.zeros(count, dtype=float),
        A_ub=-balance,
        b_ub=np.zeros(balance.shape[0], dtype=float),
        A_eq=equality,
        b_eq=response,
        bounds=[(0.0, None)] * count,
        method="highs-ds",
        options={"presolve": HIGHS_PRESOLVE},
    )
    if not feasible.success or feasible.x is None or not np.all(np.isfinite(feasible.x)):
        message = str(feasible.message) if feasible is not None else "no solver response"
        raise V21EstimatorError(f"public feasibility solve failed: {message}")
    initial = np.asarray(feasible.x, dtype=float)

    def objective(values: np.ndarray) -> float:
        return float(0.5 * np.dot(values, values))

    def gradient(values: np.ndarray) -> np.ndarray:
        return values

    constraints = [
        {"type": "eq", "fun": lambda values: equality @ values - response, "jac": lambda values: equality},
        {"type": "ineq", "fun": lambda values: balance @ values, "jac": lambda values: balance},
    ]
    optimized = minimize(
        objective,
        initial,
        jac=gradient,
        constraints=constraints,
        bounds=[(0.0, None)] * count,
        method="SLSQP",
        options={"ftol": SLSQP_FTOL, "maxiter": SLSQP_MAXITER, "disp": False},
    )
    if not optimized.success or optimized.x is None or not np.all(np.isfinite(optimized.x)):
        raise V21EstimatorError(f"public minimum-norm solve failed: {optimized.message}")
    values = np.asarray(optimized.x, dtype=float)
    max_residual = float(np.max(np.abs(equality @ values - response))) if len(response) else 0.0
    min_balance = float(np.min(balance @ values)) if balance.size else 0.0
    if not math.isfinite(max_residual) or not math.isfinite(min_balance):
        raise V21EstimatorError("public minimum-norm solve produced non-finite constraints")
    if max_residual > NORMALIZED_CONSTRAINT_TOLERANCE:
        raise V21EstimatorError("public minimum-norm solve exceeds frozen checkpoint tolerance")
    if min_balance < -NORMALIZED_CONSTRAINT_TOLERANCE:
        raise V21EstimatorError("public minimum-norm solve exceeds frozen balance tolerance")
    objective_value = objective(values)
    try:
        with np.errstate(over="raise", invalid="raise"):
            scaled_values = values * scale_m
    except FloatingPointError as error:
        raise V21EstimatorError("public minimum-norm scaling produced non-finite inferred shares") from error
    if not np.all(np.isfinite(scaled_values)):
        raise V21EstimatorError("public minimum-norm scaling produced non-finite inferred shares")
    return scaled_values, V21SolveDiagnostic(
        status="ok", message=str(optimized.message), modeled_action_count=count,
        completed_checkpoint_count=len(checkpoints), tail_action_count=0, scale_m=scale_m,
        objective=objective_value, max_checkpoint_residual_normalized=max_residual,
        min_balance_normalized=min_balance, linprog_status=int(feasible.status),
        slsqp_status=int(optimized.status), slsqp_iterations=int(getattr(optimized, "nit", 0)),
    )


def _zero_tail(action: Mapping[str, Any], positions: Mapping[str, float]) -> V21ActionEstimate:
    before = float(positions[str(action["eligible_id"])])
    return V21ActionEstimate(
        action_id=str(action["action_id"]), eligible_id=str(action["eligible_id"]), action_type=str(action["action_type"]),
        day=int(action["day"]), within_day_tick=int(action["within_day_tick"]), global_order=int(action["global_order"]),
        inferred_shares=0.0, completed=False, tail_abstention=True,
        estimated_balance_before=before, estimated_balance_after=before,
    )


def estimate(public_transcript: Sequence[Mapping[str, Any]], horizon: int) -> V21EstimateResult:
    """Estimate one causal public prefix with no access to non-public records.

    All visible actions after the final released checkpoint receive an explicit
    zero abstention.  They are present in output for evaluation accounting but
    never enter a share-total equation or update a reconstructed position.
    """

    visible_records = _visible_records(public_transcript, horizon)
    records = _validated_records(visible_records)
    visible_actions, modeled_actions, checkpoints = _causal_prefix(records)
    positions: dict[str, float] = {identifier: 0.0 for identifier in ELIGIBLE_IDS}
    estimates: list[V21ActionEstimate] = []
    if modeled_actions:
        values, diagnostic = _solve(modeled_actions, checkpoints)
        modeled_by_id = {str(action["action_id"]): (action, float(value)) for action, value in zip(modeled_actions, values)}
        for action in visible_actions:
            matched = modeled_by_id.get(str(action["action_id"]))
            if matched is None:
                estimates.append(_zero_tail(action, positions))
                continue
            public_action, amount = matched
            user = str(public_action["eligible_id"])
            before = positions[user]
            after = before + amount if public_action["action_type"] == "deposit" else before - amount
            positions[user] = after
            estimates.append(V21ActionEstimate(
                action_id=str(public_action["action_id"]), eligible_id=user, action_type=str(public_action["action_type"]),
                day=int(public_action["day"]), within_day_tick=int(public_action["within_day_tick"]),
                global_order=int(public_action["global_order"]), inferred_shares=amount, completed=True,
                tail_abstention=False, estimated_balance_before=before, estimated_balance_after=after,
            ))
        diagnostic = V21SolveDiagnostic(**{**diagnostic.__dict__, "tail_action_count": len(visible_actions) - len(modeled_actions)})
    else:
        for action in visible_actions:
            estimates.append(_zero_tail(action, positions))
        diagnostic = V21SolveDiagnostic(
            status="tail_only", message="no completed checkpoint is visible at this horizon",
            modeled_action_count=0, completed_checkpoint_count=0, tail_action_count=len(visible_actions),
            scale_m=1.0, objective=0.0, max_checkpoint_residual_normalized=0.0,
            min_balance_normalized=0.0, linprog_status=0, slsqp_status=0, slsqp_iterations=0,
        )
    return V21EstimateResult(
        final_positions=MappingProxyType(dict(positions)), action_estimates=tuple(estimates),
        completed_checkpoint_count=len(checkpoints), diagnostic=diagnostic,
    )


__all__ = [
    "ELIGIBLE_IDS", "V21ActionEstimate", "V21EstimateResult", "V21EstimatorError", "V21SolveDiagnostic", "estimate",
]
