"""Private truth-side scoring for sealed v2.1 public reconstructions.

The estimator never receives this module's records.  This is the only place
where hidden synthetic amounts and positions are joined by stable action ID.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .v21_estimator import ELIGIBLE_IDS, V21EstimateResult


@dataclass(frozen=True)
class V21PositionMetrics:
    active_eligible_participants: int
    within_10pct: float


@dataclass(frozen=True)
class V21OperationMetrics:
    completed_count: int
    completed_within_10pct: float
    tail_count: int
    tail_within_10pct: float
    all_count: int
    all_within_10pct: float


@dataclass(frozen=True)
class V21Evaluation:
    position: V21PositionMetrics
    operation: V21OperationMetrics
    true_positions: Mapping[str, int]


def _ordered_truth(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    ordered = sorted(events, key=lambda event: (int(event["global_order"]), str(event["action_id"])))
    ids = [str(event.get("action_id", "")) for event in ordered]
    if any(not identifier for identifier in ids) or len(ids) != len(set(ids)):
        raise ValueError("truth events require unique nonempty action IDs")
    for event in ordered:
        if event.get("eligible_id") not in ELIGIBLE_IDS:
            raise ValueError("truth event eligible identifier is outside the fixed roster")
        if type(event.get("shares")) is not int or int(event["shares"]) <= 0:
            raise ValueError("truth event share magnitude must be a positive integer")
        if type(event.get("position_after")) is not int or int(event["position_after"]) < 0:
            raise ValueError("truth event ending position must be a nonnegative integer")
    return ordered


def _attains(predicted: float, truth: int) -> bool:
    return abs(float(predicted) - float(truth)) <= 0.10 * float(truth)


def evaluate(truth_events: Sequence[Mapping[str, Any]], sealed: V21EstimateResult) -> V21Evaluation:
    """Score all sealed public outputs against one private causal truth prefix."""

    ordered = _ordered_truth(truth_events)
    truth_by_id = {str(event["action_id"]): event for event in ordered}
    estimates_by_id = {estimate.action_id: estimate for estimate in sealed.action_estimates}
    if len(estimates_by_id) != len(sealed.action_estimates):
        raise ValueError("sealed output contains duplicate action IDs")
    if set(estimates_by_id) != set(truth_by_id):
        raise ValueError("sealed public output and private horizon truth do not cover the same action IDs")
    positions = {identifier: 0 for identifier in ELIGIBLE_IDS}
    for event in ordered:
        positions[str(event["eligible_id"])] = int(event["position_after"])
    active = [identifier for identifier in ELIGIBLE_IDS if positions[identifier] > 0]
    denominator = len(active)
    position_p10 = (
        sum(_attains(float(sealed.final_positions.get(identifier, 0.0)), positions[identifier]) for identifier in active) / denominator
        if denominator else 0.0
    )
    completed = []
    tails = []
    for action_id, estimate in estimates_by_id.items():
        pair = (estimate, truth_by_id[action_id])
        (completed if estimate.completed else tails).append(pair)

    def fraction(pairs: Sequence[tuple[Any, Mapping[str, Any]]]) -> float:
        return sum(_attains(pair[0].inferred_shares, int(pair[1]["shares"])) for pair in pairs) / len(pairs) if pairs else 0.0

    all_pairs = [*completed, *tails]
    return V21Evaluation(
        position=V21PositionMetrics(denominator, position_p10),
        operation=V21OperationMetrics(
            completed_count=len(completed), completed_within_10pct=fraction(completed),
            tail_count=len(tails), tail_within_10pct=fraction(tails),
            all_count=len(all_pairs), all_within_10pct=fraction(all_pairs),
        ),
        true_positions=MappingProxyType(positions),
    )


def position_metrics_row(metrics: V21PositionMetrics) -> dict[str, int | float]:
    return {
        "active_eligible_participants": metrics.active_eligible_participants,
        "position_within_10pct": metrics.within_10pct,
    }


def operation_metrics_row(metrics: V21OperationMetrics) -> dict[str, int | float]:
    return {
        "completed_operation_count": metrics.completed_count,
        "completed_operation_within_10pct": metrics.completed_within_10pct,
        "tail_operation_count": metrics.tail_count,
        "tail_operation_within_10pct": metrics.tail_within_10pct,
        "all_operation_count": metrics.all_count,
        "all_operation_within_10pct": metrics.all_within_10pct,
    }


__all__ = [
    "V21Evaluation", "V21OperationMetrics", "V21PositionMetrics", "evaluate",
    "operation_metrics_row", "position_metrics_row",
]
