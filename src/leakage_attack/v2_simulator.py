"""Versioned zero-start synthetic environment for repeated-aggregate v2.

All fields on ``LatentTrace.events`` are truth-side.  Public consumers must use
:mod:`leakage_attack.v2_disclosure`, which deliberately allowlists a subset.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import math
import random
from typing import Any, Mapping

from .v2_calibration import deterministic_rng
from .v2_config import (
    DAYS,
    DEFAULT_ACTIVATION_HAZARDS,
    DEFAULT_RESIDUAL_LOG_CLIP,
    MOVING_BLOCK_DAYS,
    POPULATION_SIZE,
    TRAFFIC_MODES,
    UNIT,
)

RATE_UNIT = Decimal("1000000")
MEDIUM_ALTERNATING_RETURN_AMPLITUDE = 0.20
NANOSECONDS_PER_DAY = 86_400_000_000_000
LATENT_EVENT_FIELDS = {
    "action_id", "day", "within_day_tick", "global_order", "eligible_id", "action_type",
    "shares", "assets", "position_before", "position_after", "rate", "full_withdraw",
    "profile_log_shares", "residual_log", "aggregate_shares_after", "aggregate_assets_after",
    "activation_event", "withdrawal_reselected", "withdrawal_converted",
}


@dataclass(frozen=True)
class LatentProfile:
    eligible_id: str
    recurrence_weight: int
    deposit_log_shares: float
    withdraw_log_shares: float

    @property
    def deposit_shares(self) -> int:
        return max(1, int(round(math.exp(self.deposit_log_shares))))

    @property
    def withdraw_shares(self) -> int:
        return max(1, int(round(math.exp(self.withdraw_log_shares))))


@dataclass(frozen=True)
class LatentTrace:
    seed: int
    traffic_mode: str
    rates: list[int]
    daily_counts: list[int]
    profiles: dict[str, LatentProfile]
    events: list[dict[str, Any]]
    final_positions: dict[str, int]
    diagnostics: dict[str, int]

    @property
    def distinct_observed(self) -> int:
        return len({event["eligible_id"] for event in self.events})

    @staticmethod
    def is_full_exit_draw(value: float, probability: float = 0.02) -> bool:
        return value < probability


def bootstrap_daily_counts(counts: list[int], *, days: int = DAYS, seed: int, label: str) -> list[int]:
    """Seven-day circular moving-block bootstrap retaining zero-count days."""

    if len(counts) < 1:
        raise ValueError("daily count input cannot be empty")
    if any(not isinstance(value, int) or value < 0 for value in counts):
        raise ValueError("daily counts must be non-negative integers")
    if days <= 0:
        raise ValueError("days must be positive")
    rng = deterministic_rng(seed, f"traffic.block-bootstrap.{label}")
    out: list[int] = []
    while len(out) < days:
        start = rng.randrange(len(counts))
        out.extend(counts[(start + offset) % len(counts)] for offset in range(MOVING_BLOCK_DAYS))
    return out[:days]


def _sample_profile_log(pool: dict[str, Any], rng: random.Random) -> float:
    profiles = pool.get("profiles", [])
    if not profiles:
        raise ValueError("profile pool is empty")
    return float(rng.choice(profiles)["log_profile"])


def generate_latent_profiles(calibration: dict[str, Any], *, seed: int) -> dict[str, LatentProfile]:
    """Independently bootstrap recurrence, deposit, and withdrawal profiles."""

    weights = [int(weight) for weight in calibration.get("activity_weight_pool", []) if int(weight) > 0]
    pools = calibration.get("profile_pools", {})
    if not weights or "deposit" not in pools or "withdraw" not in pools:
        raise ValueError("v2 empirical inputs are missing bootstrap pools")
    recurrence_rng = deterministic_rng(seed, "profile.recurrence")
    deposit_rng = deterministic_rng(seed, "profile.deposit")
    withdraw_rng = deterministic_rng(seed, "profile.withdraw")
    return {
        f"u{index:03d}": LatentProfile(
            eligible_id=f"u{index:03d}",
            recurrence_weight=recurrence_rng.choice(weights),
            deposit_log_shares=_sample_profile_log(pools["deposit"], deposit_rng),
            withdraw_log_shares=_sample_profile_log(pools["withdraw"], withdraw_rng),
        )
        for index in range(POPULATION_SIZE)
    }


def _quantile_return_draw(rng: random.Random, quantiles: dict[str, float]) -> Decimal:
    anchors = [Decimal(str(quantiles.get(f"p{item:02d}", quantiles.get("p50", 0.0)))) for item in (5, 25, 50, 75, 95)]
    value = Decimal(str(rng.random())) * Decimal(4)
    index = min(3, int(value))
    fraction = value - index
    return anchors[index] + (anchors[index + 1] - anchors[index]) * fraction


def generate_v2_rates(calibration: dict[str, Any], *, seed: int, days: int = DAYS) -> list[int]:
    """Retain v1's audited quantile/alternating-rate arithmetic in v2 isolation."""

    quantiles = calibration.get("rate_quantiles", {})
    rng = deterministic_rng(seed, "rate.reward")
    rate = RATE_UNIT
    rates: list[int] = []
    for day in range(days):
        regime = 1 + ((1 if (day // 8) % 2 == 0 else -1) * MEDIUM_ALTERNATING_RETURN_AMPLITUDE)
        step_return = _quantile_return_draw(rng, quantiles) * Decimal(str(regime))
        step = max(Decimal("0.000001"), Decimal(1) + step_return)
        rate = max(1, int((rate * step).to_integral_value(rounding=ROUND_DOWN)))
        rates.append(rate)
    return rates


def _weighted_choice(ids: list[str], profiles: dict[str, LatentProfile], rng: random.Random) -> str:
    if not ids:
        raise ValueError("cannot select from no identifiers")
    return rng.choices(ids, weights=[profiles[item].recurrence_weight for item in ids], k=1)[0]


def _sample_share_magnitude(profile_log: float, residual_pool: list[float], rng: random.Random) -> tuple[int, float]:
    residual = max(-DEFAULT_RESIDUAL_LOG_CLIP, min(DEFAULT_RESIDUAL_LOG_CLIP, float(rng.choice(residual_pool or [0.0]))))
    return max(1, int(round(math.exp(profile_log + residual)))), residual


def simulate_latent_trace(
    calibration: dict[str, Any],
    *,
    seed: int,
    days: int = DAYS,
    traffic_mode: str = "known_infrastructure_excluded",
    activation_hazard: float | None = None,
    activation_hazards: Mapping[str, float] | None = None,
) -> LatentTrace:
    """Generate one new zero-state latent trace without replaying Yearn events."""

    if traffic_mode not in TRAFFIC_MODES:
        raise ValueError(f"unknown traffic mode: {traffic_mode}")
    if days <= 0:
        raise ValueError("days must be positive")
    configured_hazards = DEFAULT_ACTIVATION_HAZARDS if activation_hazards is None else activation_hazards
    if set(configured_hazards) != set(TRAFFIC_MODES):
        raise ValueError("activation hazards must cover exactly the frozen traffic modes")
    hazard = float(configured_hazards[traffic_mode]) if activation_hazard is None else float(activation_hazard)
    if not 0.0 <= hazard <= 1.0:
        raise ValueError("activation hazard must be in [0, 1]")
    daily_counts = bootstrap_daily_counts(list(calibration["daily_counts"][traffic_mode]), days=days, seed=seed, label=traffic_mode)
    profiles = generate_latent_profiles(calibration, seed=seed)
    rates = generate_v2_rates(calibration, seed=seed, days=days)
    ids = list(profiles)
    active: set[str] = set()
    positions = {identifier: 0 for identifier in ids}
    events: list[dict[str, Any]] = []
    diagnostics = {"withdrawal_reselections": 0, "withdrawal_conversions": 0, "full_withdrawals": 0, "raw_deposits": 0, "raw_withdrawals": 0}
    activation_rng = deterministic_rng(seed, "actions.activation")
    selection_rng = deterministic_rng(seed, "actions.selection")
    type_rng = deterministic_rng(seed, "actions.direction")
    full_rng = deterministic_rng(seed, "actions.full-exit")
    deposit_noise_rng = deterministic_rng(seed, "actions.deposit-residual")
    withdraw_noise_rng = deterministic_rng(seed, "actions.withdraw-residual")
    time_rng = deterministic_rng(seed, "actions.uniform-time")
    direction_counts = calibration.get("raw_filtered_direction_counts", {})
    deposits = int(direction_counts.get("deposit", 0))
    withdrawals = int(direction_counts.get("withdraw", 0))
    if deposits + withdrawals <= 0:
        raise ValueError("raw filtered direction counts must be positive")
    deposit_probability = deposits / (deposits + withdrawals)
    full_probability = float(calibration.get("full_exit_audit", {}).get("frozen_probability", 0.02))
    pools = calibration["profile_pools"]
    total_shares = 0
    serial = 0
    for day, count in enumerate(daily_counts):
        scheduled = sorted((time_rng.randrange(NANOSECONDS_PER_DAY), item) for item in range(count))
        for within_day_tick, _ in scheduled:
            # ``active`` is the observed recurrence pool, not a queue of
            # candidates.  In particular, an inactive candidate selected for
            # a withdrawal may be reselected to a funded identifier and has
            # not entered the public action transcript.  Do not consume that
            # candidate until it actually executes an action; otherwise the
            # activation hazard cannot calibrate distinct *observed* IDs.
            if not active:
                selected = activation_rng.choice(ids)
            elif len(active) < len(ids) and activation_rng.random() < hazard:
                inactive = [identifier for identifier in ids if identifier not in active]
                selected = activation_rng.choice(inactive)
            else:
                selected = _weighted_choice(sorted(active), profiles, selection_rng)
            raw_deposit = type_rng.random() < deposit_probability
            if raw_deposit:
                diagnostics["raw_deposits"] += 1
                action_type = "deposit"
                user = selected
                withdrawal_reselected = withdrawal_converted = False
            else:
                diagnostics["raw_withdrawals"] += 1
                action_type = "withdraw"
                user = selected
                withdrawal_reselected = withdrawal_converted = False
                if positions[user] <= 0:
                    funded = [identifier for identifier in sorted(active) if positions[identifier] > 0]
                    if funded:
                        user = _weighted_choice(funded, profiles, selection_rng)
                        withdrawal_reselected = True
                        diagnostics["withdrawal_reselections"] += 1
                    else:
                        action_type = "deposit"
                        withdrawal_converted = True
                        diagnostics["withdrawal_conversions"] += 1
            activation_event = user not in active
            if activation_event:
                active.add(user)
            before = positions[user]
            rate = rates[day]
            full_withdraw = False
            if action_type == "deposit":
                shares, residual = _sample_share_magnitude(profiles[user].deposit_log_shares, pools["deposit"].get("residual_log_pool", [0.0]), deposit_noise_rng)
                profile_log = profiles[user].deposit_log_shares
                positions[user] += shares
                total_shares += shares
                assets = shares * rate // UNIT
            else:
                full_withdraw = LatentTrace.is_full_exit_draw(full_rng.random(), full_probability)
                profile_log = profiles[user].withdraw_log_shares
                if full_withdraw:
                    shares, residual = before, 0.0
                    diagnostics["full_withdrawals"] += 1
                else:
                    desired, residual = _sample_share_magnitude(profile_log, pools["withdraw"].get("residual_log_pool", [0.0]), withdraw_noise_rng)
                    shares = min(desired, before)
                positions[user] -= shares
                total_shares -= shares
                assets = shares * rate // UNIT
            event = {
                "action_id": f"v2-s{seed}-a{serial:07d}", "day": day, "within_day_tick": within_day_tick,
                "global_order": serial, "eligible_id": user, "action_type": action_type, "shares": shares,
                "assets": assets, "position_before": before, "position_after": positions[user], "rate": rate,
                "full_withdraw": full_withdraw, "profile_log_shares": profile_log, "residual_log": residual,
                "aggregate_shares_after": total_shares, "aggregate_assets_after": total_shares * rate // UNIT,
                "activation_event": activation_event, "withdrawal_reselected": withdrawal_reselected,
                "withdrawal_converted": withdrawal_converted,
            }
            if set(event) != LATENT_EVENT_FIELDS or shares <= 0 or positions[user] < 0:
                raise AssertionError("invalid v2 latent accounting event")
            events.append(event)
            serial += 1
    return LatentTrace(seed, traffic_mode, rates, daily_counts, profiles, events, positions, diagnostics)


def calibrate_activation_hazard(
    evaluate_mean_distinct: Any,
    *,
    target: float = 95.0,
    iterations: int = 24,
) -> float:
    """Deterministic bisection seam; callers provide development-only evaluator."""

    low, high = 0.0, 1.0
    for _ in range(iterations):
        midpoint = (low + high) / 2
        if float(evaluate_mean_distinct(midpoint)) < target:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2
