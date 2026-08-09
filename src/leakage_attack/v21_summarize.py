"""Descriptive seed-level summaries for development-only v2.1 output.

There is intentionally no statistical threshold, confidence bound, or tested-k
choice in this module.  It reports numerical behavior of the specified
heuristic and preserves failed cells as failed cells.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .v21_config import DEVELOPMENT_SEEDS, HORIZONS, K_VALUES, TRAFFIC_MODES
from .v21_paths import prepare_new_output_root, write_new_text
from .v21_simulate import METRIC_COLUMNS, SCHEMA_VERSION

SUMMARY_COLUMNS = (
    "traffic_mode", "k", "horizon_day", "metric", "n_seed_cells", "n_successful", "n_failed", "mean",
)
_GROUP = ("traffic_mode", "k", "horizon_day")
_P10_FIELDS = (
    "position_within_10pct", "completed_operation_within_10pct",
    "tail_operation_within_10pct", "all_operation_within_10pct",
)


def _parse(value: str | None) -> Any:
    if value is None or value == "":
        return ""
    if value == "True":
        return True
    if value == "False":
        return False
    try:
        numeric = float(value)
    except ValueError:
        return value
    if not math.isfinite(numeric):
        return value
    return int(numeric) if numeric.is_integer() else numeric


def read_metrics(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != METRIC_COLUMNS:
            raise ValueError("v2.1 metrics CSV schema mismatch")
        rows = [{key: _parse(value) for key, value in row.items()} for row in reader]
    if not rows:
        raise ValueError("v2.1 metrics CSV is empty")
    return rows


def validate_matrix(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    """Require complete public cells for every supplied development seed."""

    if not rows:
        raise ValueError("v2.1 metrics rows are empty")
    keys = []
    for row in rows:
        if row.get("schema_version") != SCHEMA_VERSION or row.get("phase") != "development":
            raise ValueError("summary accepts only v2.1 development metrics")
        try:
            seed = int(row["seed"]); k = int(row["k"]); horizon = int(row["horizon_day"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("v2.1 metrics have invalid cell identifiers") from error
        if seed not in DEVELOPMENT_SEEDS or k not in K_VALUES or horizon not in HORIZONS:
            raise ValueError("v2.1 metrics contain an out-of-contract seed, k, or horizon")
        if row.get("traffic_mode") not in TRAFFIC_MODES or row.get("release") != "checkpoint_totals":
            raise ValueError("v2.1 metrics contain an unsupported traffic/release cell")
        keys.append((seed, str(row["traffic_mode"]), k, horizon))
    if len(keys) != len(set(keys)):
        raise ValueError("v2.1 metrics contain duplicate cells")
    seeds = sorted({key[0] for key in keys})
    expected = {(seed, traffic, k, horizon) for seed in seeds for traffic in TRAFFIC_MODES for k in K_VALUES for horizon in HORIZONS}
    if set(keys) != expected:
        raise ValueError("v2.1 metrics do not cover the exact one-release development matrix")
    for field in (
        "config_sha256", "semantic_config_sha256", "calibration_sha256", "source_code_fingerprint",
        "reused_v2_modules_sha256", "dependency_lock_sha256", "solver_fingerprint",
    ):
        values = {str(row.get(field, "")) for row in rows}
        if len(values) != 1 or "" in values:
            raise ValueError(f"v2.1 metrics must bind one nonempty {field}")
    for seed in seeds:
        for traffic in TRAFFIC_MODES:
            subset = [row for row in rows if int(row["seed"]) == seed and row["traffic_mode"] == traffic]
            if len({row["latent_trace_hash"] for row in subset}) != 1 or len({row["action_trace_hash"] for row in subset}) != 1:
                raise ValueError("one v2.1 seed/traffic mode must reuse one latent trace")
    return seeds


def _mean(values: Sequence[float]) -> float | str:
    return sum(values) / len(values) if values else ""


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate only complete-seed scalar outcomes, never individual actions."""

    validate_matrix(rows)
    output: list[dict[str, Any]] = []
    for traffic in TRAFFIC_MODES:
        for k in K_VALUES:
            for horizon in HORIZONS:
                current = [
                    row for row in rows
                    if row["traffic_mode"] == traffic and int(row["k"]) == k and int(row["horizon_day"]) == horizon
                ]
                # A tail-only horizon is a valid explicit abstention: no
                # numerical fit is needed because no checkpoint is public.
                # Only an actual failed cell is excluded from scored means.
                successful = [row for row in current if row.get("solver_status") in {"ok", "tail_only"}]
                failed = [row for row in current if row.get("solver_status") not in {"ok", "tail_only"}]
                base = {
                    "traffic_mode": traffic, "k": k, "horizon_day": horizon,
                    "n_seed_cells": len(current), "n_successful": len(successful), "n_failed": len(failed),
                }
                metric_values: list[tuple[str, list[float]]] = []
                for field in _P10_FIELDS:
                    values: list[float] = []
                    for row in successful:
                        value = row.get(field)
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                            raise ValueError(f"successful v2.1 cell lacks finite {field}")
                        values.append(float(value))
                    metric_values.append((field, values))
                runtimes = []
                for row in current:
                    value = row.get("solver_runtime_seconds")
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                        raise ValueError("v2.1 cell lacks finite solver runtime")
                    runtimes.append(float(value))
                tails = []
                for row in successful:
                    tail = row.get("tail_action_count")
                    actions = row.get("public_action_count")
                    if not isinstance(tail, (int, float)) or isinstance(tail, bool) or not isinstance(actions, (int, float)) or isinstance(actions, bool) or float(actions) < 0:
                        raise ValueError("successful v2.1 cell has invalid tail/action counts")
                    tails.append(float(tail) / float(actions) if float(actions) else 0.0)
                metric_values.extend((
                    ("solver_runtime_seconds", runtimes),
                    ("tail_action_rate", tails),
                    ("solver_failure_fraction", [len(failed) / len(current)]),
                ))
                for name, values in metric_values:
                    output.append({
                        "traffic_mode": traffic, "k": k, "horizon_day": horizon, "metric": name,
                        "n_seed_cells": base["n_seed_cells"], "n_successful": base["n_successful"],
                        "n_failed": base["n_failed"], "mean": _mean(values),
                    })
    if any(tuple(row) != SUMMARY_COLUMNS for row in output):
        raise AssertionError("v2.1 summary emitted an unstable schema")
    return output


def _csv_text(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        if tuple(row) != tuple(columns):
            raise AssertionError("v2.1 summary output schema mismatch")
        writer.writerow(row)
    return stream.getvalue()


def summarize_to_directory(rows: Sequence[Mapping[str, Any]], *, output: str | Path) -> dict[str, Any]:
    """Write a new external-safe descriptive summary directory."""

    seeds = validate_matrix(rows)
    summary = summarize_rows(rows)
    root = prepare_new_output_root(output)
    write_new_text(root, "development_summary.csv", _csv_text(summary, SUMMARY_COLUMNS))
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "phase": "development",
        "seeds": seeds,
        "independent_unit": "complete synthetic seed trace",
        "description": "Descriptive numerical heuristic summary only; no threshold or tested-k choice is produced.",
        "outputs": {"development_summary_rows": len(summary)},
        "external_safe": True,
        "contains_private_operation_rows": False,
    }
    write_new_text(root, "summary_metadata.json", json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    report = "\n".join((
        "# V2.1 development summary", "", f"- Seeds summarized: {len(seeds)}",
        "- Independent unit: complete synthetic seed trace.",
        "- This is descriptive development output only; it makes no threshold, confidence-bound, or tested-k choice.",
        "- Private operation-level rows are excluded from this directory.", "",
    ))
    write_new_text(root, "DEVELOPMENT_REPORT.md", report)
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a descriptive v2.1 development summary")
    parser.add_argument("--input", type=Path, required=True, help="public v2.1 metrics CSV")
    parser.add_argument("--output", type=Path, required=True, help="new summary directory")
    args = parser.parse_args(argv)
    try:
        summarize_to_directory(read_metrics(args.input), output=args.output)
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SUMMARY_COLUMNS", "main", "read_metrics", "summarize_rows", "summarize_to_directory", "validate_matrix"]
