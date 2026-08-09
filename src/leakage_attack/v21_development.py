"""Exclusive development-only writer for the isolated v2.1 lineage."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable, Mapping, Sequence

from .v21_config import (
    DEFAULT_CALIBRATION, DEFAULT_CONFIG, DEVELOPMENT_SEEDS, SCHEMA_VERSION,
    ResolvedV21Config, load_development_config,
)
from .v21_paths import CANONICAL_DEVELOPMENT_ROOT, create_child_directory, prepare_new_output_root, write_new_bytes, write_new_text
from .v21_simulate import (
    METRIC_COLUMNS, PRIVATE_TRUTH_JOIN_COLUMNS, PUBLIC_ACTION_ESTIMATE_COLUMNS,
    SOLVER_DIAGNOSTIC_COLUMNS, TRAFFIC_DIAGNOSTIC_COLUMNS, V21SeedArtifacts, run_seed_artifacts,
)
from .v21_summarize import summarize_to_directory


def _csv_bytes(rows: Iterable[Mapping[str, Any]], columns: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for raw in rows:
        row = dict(raw)
        if tuple(row) != tuple(columns):
            raise AssertionError("v2.1 writer received a row with an unstable schema")
        writer.writerow(row)
    return stream.getvalue().encode("utf-8")


def _gzip_csv_bytes(rows: Iterable[Mapping[str, Any]], columns: Sequence[str]) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed:
        compressed.write(_csv_bytes(rows, columns))
    return raw.getvalue()


def _write_seed(public_root: Path, private_root: Path, seed: int, artifacts: V21SeedArtifacts) -> None:
    public_seed = create_child_directory(public_root, f"seed_{seed:05d}")
    private_seed = create_child_directory(private_root, f"seed_{seed:05d}")
    write_new_bytes(public_seed, "metrics.csv", _csv_bytes(artifacts.metrics, METRIC_COLUMNS))
    write_new_bytes(public_seed, "solver_diagnostics.csv", _csv_bytes(artifacts.solver_diagnostics, SOLVER_DIAGNOSTIC_COLUMNS))
    write_new_bytes(public_seed, "action_estimates.csv.gz", _gzip_csv_bytes(artifacts.public_action_estimates, PUBLIC_ACTION_ESTIMATE_COLUMNS))
    write_new_bytes(public_seed, "traffic_diagnostics.csv", _csv_bytes(artifacts.traffic_diagnostics, TRAFFIC_DIAGNOSTIC_COLUMNS))
    # This file is deliberately under the private tree.  No summary or public
    # shard file may contain its truth columns.
    write_new_bytes(private_seed, "truth_join.csv.gz", _gzip_csv_bytes(artifacts.private_truth_joins, PRIVATE_TRUTH_JOIN_COLUMNS))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_checksums(root: Path) -> None:
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("v2.1 checksum inventory rejects symlink/nonregular files")
        lines.append(f"{_file_sha256(path)}  {path.relative_to(root).as_posix()}")
    write_new_text(root, "SHA256SUMS", "\n".join(lines) + "\n")


def _validate_seed_set(seeds: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(seeds)
    if not normalized or any(type(seed) is not int or seed not in DEVELOPMENT_SEEDS for seed in normalized):
        raise ValueError("v2.1 run seeds must be unique members of 41001..41030")
    if tuple(sorted(normalized)) != normalized or len(set(normalized)) != len(normalized):
        raise ValueError("v2.1 run seeds must be strictly ascending and unique")
    return normalized


def run_development(
    *,
    output: str | Path,
    seeds: Sequence[int] = DEVELOPMENT_SEEDS,
    resolved: ResolvedV21Config | None = None,
    config_path: str | Path = DEFAULT_CONFIG,
    calibration_path: str | Path = DEFAULT_CALIBRATION,
) -> dict[str, Any]:
    """Run a new isolated development root; confirmation is not implemented here."""

    requested = _validate_seed_set(seeds)
    if resolved is None:
        resolved = load_development_config(config_path, calibration_path)
    output_path = Path(output).expanduser()
    if output_path.resolve(strict=False) == CANONICAL_DEVELOPMENT_ROOT.resolve() and requested != DEVELOPMENT_SEEDS:
        raise ValueError("the canonical v2.1 development root requires the complete 41001..41030 domain")
    root = prepare_new_output_root(output_path)
    public_root = create_child_directory(root, "public")
    private_root = create_child_directory(root, "private")
    all_metrics: list[dict[str, Any]] = []
    all_diagnostics: list[dict[str, Any]] = []
    all_traffic: list[dict[str, Any]] = []
    provenance: Mapping[str, str] | None = None
    source_manifest: Mapping[str, Any] | None = None
    for seed in requested:
        artifacts = run_seed_artifacts(seed, resolved=resolved)
        if provenance is None:
            provenance = artifacts.provenance
            source_manifest = artifacts.source_manifest
        elif dict(provenance) != dict(artifacts.provenance) or dict(source_manifest or {}) != dict(artifacts.source_manifest):
            raise RuntimeError("v2.1 seed artifacts have inconsistent provenance")
        _write_seed(public_root, private_root, seed, artifacts)
        all_metrics.extend(artifacts.metrics)
        all_diagnostics.extend(artifacts.solver_diagnostics)
        all_traffic.extend(artifacts.traffic_diagnostics)
    if provenance is None or source_manifest is None:
        raise AssertionError("v2.1 development run produced no seed artifacts")
    write_new_bytes(public_root, "metrics.csv", _csv_bytes(all_metrics, METRIC_COLUMNS))
    write_new_bytes(public_root, "solver_diagnostics.csv", _csv_bytes(all_diagnostics, SOLVER_DIAGNOSTIC_COLUMNS))
    write_new_bytes(public_root, "traffic_diagnostics.csv", _csv_bytes(all_traffic, TRAFFIC_DIAGNOSTIC_COLUMNS))
    complete = requested == DEVELOPMENT_SEEDS
    summary_metadata: dict[str, Any] | None = None
    if complete:
        summary_metadata = summarize_to_directory(all_metrics, output=public_root / "summary")
    write_new_text(root, "executed_config.json", json.dumps(dict(resolved.raw), sort_keys=True, indent=2) + "\n")
    write_new_text(root, "source_files.json", json.dumps(source_manifest, sort_keys=True, indent=2) + "\n")
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "phase": "development",
        "seeds": list(requested),
        "configured_development_seed_range": [DEVELOPMENT_SEEDS[0], DEVELOPMENT_SEEDS[-1]],
        "complete_development_domain": complete,
        "cells_per_seed": 120,
        "release": "checkpoint_totals",
        "claim_boundary": "development-only deterministic numerical public-prefix minimum-norm heuristic; not confirmation, qualification, or paper evidence",
        "provenance": dict(provenance),
        "public_private_layout": {
            "public": "metrics, numerical diagnostics, and public action estimates only",
            "private": "truth joins used only after sealed public estimation",
        },
        "summary": summary_metadata,
    }
    write_new_text(root, "run_metadata.json", json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    _write_checksums(root)
    return metadata


__all__ = ["run_development"]
