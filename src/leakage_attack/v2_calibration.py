"""Deterministic Stage-A-to-v2 empirical input builder.

The builder consumes audited Stage A summaries only to calibrate a new synthetic
zero-state environment.  It never replays source events as v2 actions.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .v2_config import DEFAULT_RESIDUAL_LOG_CLIP, DEFAULT_SHRINKAGE_ADDEND, UNIT, canonical_json_sha256, file_sha256
from .v2_paths import assert_not_within_immutable_v1_root

SECONDS_PER_DAY = 86_400


def deterministic_rng(seed: int, label: str) -> random.Random:
    """Return a component RNG derived without Python's randomized hash()."""

    material = f"repeated_aggregate_nnls_v2\0{int(seed)}\0{label}".encode("utf-8")
    return random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _positive_microshares(value: str | float | int, unit: int) -> int | None:
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    amount = int((parsed * unit).to_integral_value(rounding=ROUND_HALF_UP))
    return amount if amount > 0 else None


def _log_median(values: Iterable[int]) -> float:
    return float(median([math.log(value) for value in values]))


def stabilized_profile_pool(
    rows: Iterable[dict[str, str]],
    *,
    direction: str,
    unit: int = UNIT,
    shrinkage_addend: int = DEFAULT_SHRINKAGE_ADDEND,
    residual_clip: float = DEFAULT_RESIDUAL_LOG_CLIP,
) -> dict[str, Any]:
    """Build count-shrunk address profiles in canonical share units.

    Each filtered address is retained in the sampling pool.  An address with no
    observations in this direction receives the declared direction-global log
    median rather than an invented address-specific amount.
    """

    if direction not in {"deposit", "withdraw"}:
        raise ValueError("direction must be deposit or withdraw")
    if shrinkage_addend < 0:
        raise ValueError("shrinkage addend must be non-negative")
    by_address: dict[str, list[int]] = defaultdict(list)
    all_addresses: set[str] = set()
    excluded_nonpositive = 0
    for row in rows:
        address = str(row.get("owner", ""))
        if not address:
            continue
        all_addresses.add(address)
        if row.get("action") != direction:
            continue
        value = _positive_microshares(row.get("shares", ""), unit)
        if value is None:
            excluded_nonpositive += 1
            continue
        by_address[address].append(value)
    observed = [value for values in by_address.values() for value in values]
    if not observed:
        raise ValueError(f"no positive {direction} share observations")
    global_log_median = _log_median(observed)
    profiles: list[dict[str, Any]] = []
    residuals: list[float] = []
    for address in sorted(all_addresses):
        values = by_address.get(address, [])
        support = len(values)
        if support:
            raw_log_median = _log_median(values)
            alpha = support / (support + shrinkage_addend)
            log_profile = alpha * raw_log_median + (1.0 - alpha) * global_log_median
            residuals.extend(max(-residual_clip, min(residual_clip, math.log(value) - raw_log_median)) for value in values)
        else:
            raw_log_median = None
            alpha = 0.0
            log_profile = global_log_median
        profiles.append({
            "address": address,
            "support": support,
            "raw_log_median": raw_log_median,
            "shrinkage_alpha": alpha,
            "log_profile": log_profile,
            "imputed_missing_direction": support == 0,
        })
    return {
        "direction": direction,
        "unit": "microshares_per_operation",
        "support_address_count": len(by_address),
        "positive_observation_count": len(observed),
        "nonpositive_observations_excluded": excluded_nonpositive,
        "global_log_median": global_log_median,
        "missing_direction_log_imputation": global_log_median,
        "shrinkage": {"formula": "alpha=n/(n+5); log_profile=alpha*address_log_median+(1-alpha)*global_log_median", "addend": shrinkage_addend},
        "residual_transform": {"formula": "log(share)-address_log_median", "clip_abs": residual_clip},
        "profiles": profiles,
        "residual_log_pool": residuals or [0.0],
    }


def _daily_counts(rows: list[dict[str, str]], predicate: Any, minimum_day: int, maximum_day: int) -> list[int]:
    counts = [0] * (maximum_day - minimum_day + 1)
    for row in rows:
        if predicate(row):
            counts[int(row["timestamp"]) // SECONDS_PER_DAY - minimum_day] += 1
    return counts


def _rate_quantiles(parameters: dict[str, Any]) -> dict[str, float]:
    summary = parameters.get("exchange_rate_calibration", {}).get("cleaned_return_series_summary", {})
    return {name: float(summary.get(name, 0.0) or 0.0) for name in ("p05", "p25", "p50", "p75", "p95")}


def build_empirical_inputs(
    results_dir: str | Path = "results",
    source_metadata_path: str | Path | None = None,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write `v2_empirical_inputs.json` deterministically from Stage A artifacts."""

    results = Path(results_dir)
    state_path = results / "state_reconstructed_events.csv"
    input_audit_path = results / "input_audit.csv"
    parameters_path = results / "calibrated_parameters.json"
    if source_metadata_path is None:
        source_metadata_path = results.parent / "data" / "raw" / "source_metadata.json"
    source_path = Path(source_metadata_path)
    rows = _read_rows(state_path)
    parameters = json.loads(parameters_path.read_text())
    source_metadata = json.loads(source_path.read_text())
    valid_rows = [row for row in rows if row.get("timestamp", "").strip()]
    if not valid_rows:
        raise ValueError("state reconstruction has no timestamped events")
    timestamps = [int(row["timestamp"]) for row in valid_rows]
    first_day, last_day = min(timestamps) // SECONDS_PER_DAY, max(timestamps) // SECONDS_PER_DAY
    filtered = [row for row in valid_rows if row.get("owner_classification") != "known_infrastructure"]
    all_owners = sorted({row.get("owner", "") for row in filtered if row.get("owner", "")})
    recurrence = Counter(row["owner"] for row in filtered if row.get("owner", ""))
    deposit_pool = stabilized_profile_pool(filtered, direction="deposit")
    withdraw_pool = stabilized_profile_pool(filtered, direction="withdraw")
    raw_direction_counts = Counter(row.get("action") for row in filtered)
    all_withdrawals = [row for row in valid_rows if row.get("action") == "withdraw"]
    full_exits = [row for row in all_withdrawals if row.get("withdrawal_class") == "full_estimate"]
    excluded = deposit_pool["nonpositive_observations_excluded"] + withdraw_pool["nonpositive_observations_excluded"]
    payload: dict[str, Any] = {
        "schema": "repeated_aggregate_nnls_v2_empirical_inputs",
        "purpose": "Stage A calibration only; source events are not replayed as v2 vault actions.",
        "profiles_identity_language": "pseudonymous address-level profiles, not humans",
        "day_basis": {"timezone": "UTC", "first_epoch_day": first_day, "last_epoch_day": last_day, "zero_inclusive": True},
        "daily_counts": {
            "all_addresses": _daily_counts(valid_rows, lambda _: True, first_day, last_day),
            "known_infrastructure_excluded": _daily_counts(filtered, lambda _: True, first_day, last_day),
        },
        "activity_weight_pool": [recurrence[address] for address in all_owners],
        "activity_weight_records": [{"address": address, "count": recurrence[address]} for address in all_owners],
        "profile_pools": {"deposit": deposit_pool, "withdraw": withdraw_pool},
        "raw_filtered_direction_counts": {"deposit": raw_direction_counts["deposit"], "withdraw": raw_direction_counts["withdraw"]},
        "share_exclusions": {"nonpositive": excluded, "deposit_nonpositive": deposit_pool["nonpositive_observations_excluded"], "withdraw_nonpositive": withdraw_pool["nonpositive_observations_excluded"]},
        "full_exit_audit": {"full_estimate_count": len(full_exits), "all_address_withdrawal_count": len(all_withdrawals), "audited_fraction": len(full_exits) / len(all_withdrawals) if all_withdrawals else None, "frozen_probability": 0.02, "frozen_rationale": "audited all-address 10/501 lower-bound-style estimate under left-censored history"},
        "rate_quantiles": _rate_quantiles(parameters),
        "provenance": {
            "state_reconstructed_events_sha256": file_sha256(state_path),
            "input_audit_sha256": file_sha256(input_audit_path),
            "calibrated_parameters_sha256": file_sha256(parameters_path),
            "source_metadata_sha256": file_sha256(source_path),
            "source": source_metadata,
            "rate_generator": "v1 audited Yearn-quantile return generator retained numerically; same-day fixed rate",
        },
    }
    payload["artifact_sha256"] = canonical_json_sha256(payload)
    target = Path(output_path) if output_path is not None else results / "v2_empirical_inputs.json"
    assert_not_within_immutable_v1_root(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    """Small CLI used only to regenerate the allowed calibration artifact."""

    import argparse
    parser = argparse.ArgumentParser(description="Build v2 empirical calibration inputs")
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--source-metadata", type=Path, default=Path("data/raw/source_metadata.json"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    build_empirical_inputs(args.results, args.source_metadata, output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
