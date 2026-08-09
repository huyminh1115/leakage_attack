"""CLI for a fresh, explicitly experimental V50 output directory."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

from .v50 import DEVELOPMENT_SEEDS, K_VALUES, OPERATION_HORIZON, generate_trace, run_seed_k


def _write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def run(output: Path, *, seeds: tuple[int, ...], ks: tuple[int, ...], operations: int) -> dict[str, object]:
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    summaries: list[dict[str, object]] = []
    trajectory: list[dict[str, object]] = []
    for seed in seeds:
        trace = generate_trace(seed, operations=operations)
        for k in ks:
            result = run_seed_k(seed, k, operations=operations, trace=trace)
            summaries.append({"seed": seed, "k": k, "release_count": result.release_count, "censored_tail_actor_count": result.censored_tail_actor_count, "primary_l10": result.primary_l10, "primary_s10": result.primary_s10})
            trajectory.extend({"seed": seed, "k": k, "snapshot": item.index, "warmup": item.warmup, "lambda": item.lambda_value, "l10": item.l10, "s10": item.s10, "truth_active_actor_count": item.active_actor_count, "zero_actor_count": item.zero_actor_count} for item in result.snapshot_scores)
    _write_csv(output / "run_summary.csv", summaries, ["seed", "k", "release_count", "censored_tail_actor_count", "primary_l10", "primary_s10"])
    _write_csv(output / "snapshot_trajectory.csv", trajectory, ["seed", "k", "snapshot", "warmup", "lambda", "l10", "s10", "truth_active_actor_count", "zero_actor_count"])
    metadata = {"schema_version": "v50_experimental_r1", "claim_boundary": "Experimental synthetic stable-profile attacker only; no safe-k selection or deployed/cryptographic safety claim.", "seeds": list(seeds), "k_values": list(ks), "operations_per_seed_trace": operations, "public_artifacts": ["run_summary.csv", "snapshot_trajectory.csv"]}
    (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run independent experimental V50 leakage simulation")
    parser.add_argument("--output", type=Path, required=True, help="new output directory")
    parser.add_argument("--seed", type=int, action="append", dest="seeds", help="repeat; defaults to 50001..50010")
    parser.add_argument("--k", type=int, action="append", dest="ks", help="repeat; defaults to V50 grid")
    parser.add_argument("--operations", type=int, default=OPERATION_HORIZON, help="staging override; default is 10000")
    args = parser.parse_args(argv)
    seeds = tuple(args.seeds) if args.seeds else DEVELOPMENT_SEEDS
    ks = tuple(args.ks) if args.ks else K_VALUES
    if not seeds or any(seed not in DEVELOPMENT_SEEDS for seed in seeds) or len(set(seeds)) != len(seeds): parser.error("seeds must be unique V50 public seeds")
    if not ks or any(k not in K_VALUES for k in ks) or len(set(ks)) != len(ks): parser.error("k must be unique V50 grid values")
    if args.operations <= 0: parser.error("operations must be positive")
    try: metadata = run(args.output, seeds=seeds, ks=ks, operations=args.operations)
    except (OSError, ValueError) as error: parser.error(str(error))
    print(json.dumps(metadata, sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
