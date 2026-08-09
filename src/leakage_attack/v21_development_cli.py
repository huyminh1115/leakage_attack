"""Console entry point for a fresh, development-only v2.1 run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .v21_config import DEFAULT_CALIBRATION, DEFAULT_CONFIG, DEVELOPMENT_SEEDS, load_development_config
from .v21_development import run_development
from .v21_paths import CANONICAL_DEVELOPMENT_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the development-only public-checkpoint minimum-norm v2.1 study"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument(
        "--output", type=Path, default=CANONICAL_DEVELOPMENT_ROOT,
        help="new output root; the canonical root is allowed only for all 30 development seeds",
    )
    parser.add_argument(
        "--seed", type=int, action="append", dest="seeds",
        help="repeat for a sorted staging subset; omit to run all development seeds",
    )
    args = parser.parse_args(argv)
    seeds = tuple(args.seeds) if args.seeds is not None else DEVELOPMENT_SEEDS
    try:
        resolved = load_development_config(args.config, args.calibration)
        metadata = run_development(output=args.output, seeds=seeds, resolved=resolved)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
