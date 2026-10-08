"""Verify the public paper bundle and print its existing day-365 percentages."""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
from pathlib import Path

BUNDLE = (Path(__file__).resolve().parents[1] / "results" /
          "public_checkpoint_min_norm_v21_development_30_r2_paper")
FIELD = "filtered_completed_operation_p10_day365"
CATEGORIES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30, 40, 50)


def verify_bundle() -> int:
    count = 0
    for line in (BUNDLE / "SHA256SUMS").read_text().splitlines():
        if not line.strip():
            continue
        expected, name = line.split(maxsplit=1)
        file = (BUNDLE / name.lstrip("*")).resolve()
        if not file.is_relative_to(BUNDLE.resolve()):
            raise ValueError(f"Checksum path escapes the bundle: {name}")
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch: {name}")
        count += 1
    if count == 0:
        raise ValueError("Empty checksum inventory")
    return count


def table_rows() -> list[tuple[int, float]]:
    with (BUNDLE / "v21_descriptive_results_source.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if tuple(int(row["k"]) for row in rows) != CATEGORIES:
        raise ValueError("Unexpected or incomplete strict-k categories")
    result = []
    for row in rows:
        rate = float(row[FIELD])
        if int(row["n_seeds"]) != 30 or not math.isfinite(rate) or not 0 <= rate <= 1:
            raise ValueError(f"Invalid table record for k={row['k']}")
        result.append((int(row["k"]), rate))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        count = verify_bundle()
        rows = [] if args.verify_only else table_rows()
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Paper artifact check failed: {error}\n")
    print(f"Verified {count} public bundle files.")
    if not args.verify_only:
        print("k,within_10pct_percent")
        for k, rate in rows:
            print(f"{k},{100 * rate:.2f}%")


if __name__ == "__main__":
    main()
