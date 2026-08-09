"""Independent V50 synthetic leakage experiment.

V50 deliberately does not reuse the V2.1 estimator or evidence roots. The
public estimator accepts only released memberships, aggregates, and cumulative
operation counts; private amounts/balances remain in the simulator/evaluator.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import nnls

POPULATION_SIZE = 100
K_VALUES = (1, 2, 3, 5, 6, 8, 10, 20, 30, 50)
DEVELOPMENT_SEEDS = tuple(range(50001, 50011))
OPERATION_HORIZON = 10_000
WARMUP_RELEASES = 10
ROLLING_LOSS_WINDOW = 50
LAMBDA_MULTIPLIERS = (1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0)
ACTORS = tuple(f"a{index:03d}" for index in range(POPULATION_SIZE))


@dataclass(frozen=True)
class Operation:
    order: int
    actor: str
    direction: str
    deposit_count: int
    withdrawal_count: int
    amount: int
    true_balance: int


@dataclass(frozen=True)
class PublicRelease:
    index: int
    actors: tuple[str, ...]
    aggregate_shares: int
    deposit_counts: tuple[int, ...]
    withdrawal_counts: tuple[int, ...]


@dataclass(frozen=True)
class TruthSnapshot:
    balances: tuple[int, ...]


@dataclass(frozen=True)
class ReleaseBuild:
    public: tuple[PublicRelease, ...]
    truth: tuple[TruthSnapshot, ...]
    censored_tail_actor_count: int


@dataclass(frozen=True)
class SnapshotScore:
    index: int
    warmup: bool
    lambda_value: float
    l10: float
    s10: float
    active_actor_count: int
    zero_actor_count: int
    predictions: tuple[float, ...]


@dataclass(frozen=True)
class RunResult:
    seed: int
    k: int
    snapshot_scores: tuple[SnapshotScore, ...]
    release_count: int
    censored_tail_actor_count: int
    primary_l10: float | None
    primary_s10: float | None


def actor_index(actor: str) -> int:
    if actor not in ACTORS:
        raise ValueError("actor is outside the V50 fixed roster")
    return int(actor[1:])


def generate_trace(seed: int, *, operations: int = OPERATION_HORIZON) -> tuple[Operation, ...]:
    """Create one zero-start private trace reused across all k values."""
    if type(seed) is not int or type(operations) is not int or operations <= 0:
        raise ValueError("seed must be an int and operations must be positive")
    rng = np.random.default_rng(seed)
    # lognormal median 100, GSD 2; integer and never zero.
    profiles = np.maximum(1, np.rint(rng.lognormal(math.log(100.0), math.log(2.0), POPULATION_SIZE))).astype(int)
    balances = np.zeros(POPULATION_SIZE, dtype=np.int64)
    deposits = np.zeros(POPULATION_SIZE, dtype=np.int64)
    withdrawals = np.zeros(POPULATION_SIZE, dtype=np.int64)
    events: list[Operation] = []
    noise_sigma = math.log(1.25)
    for order in range(operations):
        index = int(rng.integers(0, POPULATION_SIZE))
        # Count feasibility is intentionally stronger than monetary feasibility.
        force_deposit = balances[index] == 0 or deposits[index] == withdrawals[index]
        deposit = force_deposit or bool(rng.integers(0, 2) == 0)
        multiplier = math.exp(float(rng.normal(0.0, noise_sigma)) - noise_sigma**2 / 2.0)
        requested = max(1, int(round(int(profiles[index]) * multiplier)))
        if deposit:
            amount = requested
            balances[index] += amount
            deposits[index] += 1
            direction = "deposit"
        else:
            amount = min(requested, int(balances[index]))
            balances[index] -= amount
            withdrawals[index] += 1
            direction = "withdraw"
        if balances[index] < 0 or withdrawals[index] > deposits[index]:
            raise AssertionError("V50 generator violated balance/count feasibility")
        events.append(Operation(order, ACTORS[index], direction, int(deposits[index]), int(withdrawals[index]), amount, int(balances[index])))
    return tuple(events)


def build_releases(trace: Sequence[Operation], k: int) -> ReleaseBuild:
    """Strictly release on exactly k new actors, then reset; never flush tail."""
    if k not in K_VALUES:
        raise ValueError("k is outside the V50 grid")
    balances = np.zeros(POPULATION_SIZE, dtype=np.int64)
    deposits = np.zeros(POPULATION_SIZE, dtype=np.int64)
    withdrawals = np.zeros(POPULATION_SIZE, dtype=np.int64)
    seen: set[str] = set()
    public: list[PublicRelease] = []
    truth: list[TruthSnapshot] = []
    for event in trace:
        index = actor_index(event.actor)
        if event.direction == "deposit":
            deposits[index] += 1; balances[index] += event.amount
        elif event.direction == "withdraw":
            withdrawals[index] += 1; balances[index] -= event.amount
        else:
            raise ValueError("V50 trace direction is invalid")
        if balances[index] < 0 or withdrawals[index] > deposits[index]:
            raise ValueError("V50 trace is infeasible")
        seen.add(event.actor)
        if len(seen) == k:
            members = tuple(sorted(seen))
            aggregate = int(sum(int(balances[actor_index(actor)]) for actor in members))
            public.append(PublicRelease(len(public), members, aggregate, tuple(map(int, deposits)), tuple(map(int, withdrawals))))
            truth.append(TruthSnapshot(tuple(map(int, balances))))
            seen.clear()
    return ReleaseBuild(tuple(public), tuple(truth), len(seen))


def _validate_public_release(release: PublicRelease, previous: PublicRelease | None = None) -> np.ndarray:
    if not isinstance(release, PublicRelease) or len(release.actors) == 0 or len(set(release.actors)) != len(release.actors):
        raise ValueError("public release membership is malformed")
    if release.aggregate_shares < 0 or len(release.deposit_counts) != POPULATION_SIZE or len(release.withdrawal_counts) != POPULATION_SIZE:
        raise ValueError("public release has invalid counts or aggregate")
    deposits = np.asarray(release.deposit_counts, dtype=float)
    withdrawals = np.asarray(release.withdrawal_counts, dtype=float)
    if previous is not None:
        previous_deposits = np.asarray(previous.deposit_counts, dtype=float)
        previous_withdrawals = np.asarray(previous.withdrawal_counts, dtype=float)
        if np.any(deposits < previous_deposits):
            raise ValueError("public cumulative deposit count regresses")
        if np.any(withdrawals < previous_withdrawals):
            raise ValueError("public cumulative withdrawal count regresses")
    counts = deposits - withdrawals
    if np.any(counts < 0):
        raise ValueError("public count prefix violates nonnegative one-profile balance")
    row = np.zeros(POPULATION_SIZE, dtype=float)
    for actor in release.actors:
        row[actor_index(actor)] = counts[actor_index(actor)]
    return row


def lambda_grid(gram: np.ndarray) -> tuple[float, ...]:
    if gram.shape != (POPULATION_SIZE, POPULATION_SIZE):
        raise ValueError("V50 Gram matrix has an invalid shape")
    scale = max(1.0, float(np.trace(gram)) / POPULATION_SIZE)
    return tuple(scale * value for value in LAMBDA_MULTIPLIERS)


def _ridge_nonnegative(gram: np.ndarray, response: np.ndarray, ridge: float, initial: np.ndarray | None = None) -> np.ndarray:
    """Solve the non-negative ridge objective exactly enough to satisfy its KKT conditions.

    ``initial`` is intentionally retained for the estimator's call signature, but
    SciPy's active-set NNLS solver has no warm-start interface.  The positive
    ridge term makes ``gram + ridge * I`` positive definite, so its Cholesky
    factor converts the sufficient-statistics objective into an equivalent NNLS
    problem without retaining private or historical raw rows.
    """
    if ridge <= 0 or not math.isfinite(ridge):
        raise ValueError("ridge must be finite and positive")
    if gram.shape != (POPULATION_SIZE, POPULATION_SIZE) or response.shape != (POPULATION_SIZE,):
        raise ValueError("V50 ridge sufficient statistics have invalid shapes")
    del initial  # The exact active-set solver does not accept a warm start.
    system = gram + ridge * np.eye(POPULATION_SIZE, dtype=float)
    # Actors absent from every public design row have an independent optimum of
    # zero.  Restricting the active solve avoids repeatedly factorising 100x100
    # matrices during sparse early prefixes (especially k=1) without changing
    # the objective.
    support = np.flatnonzero(np.diag(gram) > 0.0)
    values = np.zeros(POPULATION_SIZE, dtype=float)
    try:
        if support.size:
            active_system = system[np.ix_(support, support)]
            active_response = response[support]
            off_diagonal = active_system - np.diag(np.diag(active_system))
            if np.count_nonzero(off_diagonal) == 0:
                active_values = np.maximum(0.0, active_response / np.diag(active_system))
            else:
                lower = np.linalg.cholesky(active_system)
                transformed_response = np.linalg.solve(lower, active_response)
                active_values, _ = nnls(lower.T, transformed_response, maxiter=30 * support.size)
            values[support] = active_values
    except (np.linalg.LinAlgError, RuntimeError) as error:
        raise RuntimeError("V50 non-negative ridge solver failed to converge") from error

    gradient = system @ values - response
    value_scale = max(1.0, float(np.max(np.abs(values))))
    gradient_scale = max(
        1.0,
        float(np.max(np.abs(response))),
        float(np.linalg.norm(system, ord=np.inf)) * value_scale,
    )
    tolerance = 1e-8 * gradient_scale
    positive = values > 1e-10 * value_scale
    stationarity = float(np.max(np.abs(gradient[positive]))) if np.any(positive) else 0.0
    dual_feasibility = float(np.max(np.maximum(-gradient[~positive], 0.0))) if np.any(~positive) else 0.0
    if not np.all(np.isfinite(values)) or min(stationarity, dual_feasibility) < 0 or max(stationarity, dual_feasibility) > tolerance:
        raise RuntimeError(
            "V50 non-negative ridge solver failed KKT convergence check "
            f"(stationarity={stationarity:.3e}, dual={dual_feasibility:.3e}, tolerance={tolerance:.3e})"
        )
    return values


def estimate_public(releases: Sequence[PublicRelease]) -> tuple[SnapshotScore, ...]:
    """Causal prequential V50 attacker; no truth-side input is accepted."""
    gram = np.zeros((POPULATION_SIZE, POPULATION_SIZE), dtype=float)
    response = np.zeros(POPULATION_SIZE, dtype=float)
    candidate_losses = {multiplier: [] for multiplier in LAMBDA_MULTIPLIERS}
    candidate_states = {multiplier: np.zeros(POPULATION_SIZE, dtype=float) for multiplier in LAMBDA_MULTIPLIERS}
    scores: list[SnapshotScore] = []
    previous_release: PublicRelease | None = None
    for index, release in enumerate(releases):
        row = _validate_public_release(release, previous_release)
        previous_release = release
        current_grid = lambda_grid(gram)
        # Before observing Y_t, independently predict it with every candidate.
        prior_count = index
        for multiplier, ridge in zip(LAMBDA_MULTIPLIERS, current_grid):
            state = _ridge_nonnegative(gram, response, ridge, candidate_states[multiplier])
            candidate_states[multiplier] = state
            candidate_losses[multiplier].append(float((float(row @ state) - release.aggregate_shares) ** 2))
        if prior_count < WARMUP_RELEASES:
            selected_multiplier = LAMBDA_MULTIPLIERS[-1]
        else:
            # Stable argmin iterates increasing multipliers and ties choose larger.
            selected_multiplier = min(LAMBDA_MULTIPLIERS, key=lambda m: (float(np.mean(candidate_losses[m][-ROLLING_LOSS_WINDOW:])), -m))
        selected_lambda = current_grid[LAMBDA_MULTIPLIERS.index(selected_multiplier)]
        # Update only after lambda selection and the release's public aggregate.
        gram += np.outer(row, row)
        response += row * float(release.aggregate_shares)
        prediction = _ridge_nonnegative(gram, response, selected_lambda, candidate_states[selected_multiplier])
        candidate_states[selected_multiplier] = prediction
        # Truth is deliberately not scored here: evaluator owns that join.
        scores.append(SnapshotScore(index, prior_count < WARMUP_RELEASES, selected_lambda, math.nan, math.nan, 0, 0, tuple(map(float, prediction))))
    return tuple(scores)


def evaluate(releases: Sequence[PublicRelease], truth: Sequence[TruthSnapshot], public_scores: Sequence[SnapshotScore]) -> tuple[SnapshotScore, ...]:
    if len(releases) != len(truth) or len(truth) != len(public_scores):
        raise ValueError("public estimates and private snapshots do not align")
    evaluated: list[SnapshotScore] = []
    for score, snapshot in zip(public_scores, truth):
        balances = np.asarray(snapshot.balances, dtype=float)
        predicted = np.asarray(score.predictions, dtype=float)
        active = balances > 0
        active_count = int(np.sum(active))
        l10 = float(np.mean(np.abs(predicted[active] - balances[active]) / balances[active] <= 0.10)) if active_count else 0.0
        evaluated.append(SnapshotScore(score.index, score.warmup, score.lambda_value, l10, 1.0 - l10, active_count, POPULATION_SIZE - active_count, score.predictions))
    return tuple(evaluated)


def run_seed_k(seed: int, k: int, *, operations: int = OPERATION_HORIZON, trace: Sequence[Operation] | None = None) -> RunResult:
    source = tuple(trace) if trace is not None else generate_trace(seed, operations=operations)
    build = build_releases(source, k)
    evaluated = evaluate(build.public, build.truth, estimate_public(build.public))
    primary = [row for row in evaluated if not row.warmup]
    primary_l10 = float(np.mean([row.l10 for row in primary])) if primary else None
    return RunResult(seed, k, evaluated, len(evaluated), build.censored_tail_actor_count, primary_l10, None if primary_l10 is None else 1.0 - primary_l10)


__all__ = ["ACTORS", "DEVELOPMENT_SEEDS", "K_VALUES", "LAMBDA_MULTIPLIERS", "OPERATION_HORIZON", "Operation", "PublicRelease", "ReleaseBuild", "RunResult", "SnapshotScore", "TruthSnapshot", "build_releases", "estimate_public", "evaluate", "generate_trace", "lambda_grid", "run_seed_k"]
