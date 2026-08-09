#!/usr/bin/env python3
"""Generate V2.1 descriptive paper artifacts from the authenticated public r2 summary.

This presentation-only script intentionally lives outside ``src/leakage_attack``.
It consumes aggregate, external-safe V2.1 development-summary material and
provenance metadata only; it never opens the ``private/`` truth-join tree,
row-level metrics, or public action-estimate files.  The output is an exclusive
sibling bundle, never a mutation of the development root.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import shutil
import stat
import struct
import subprocess
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve()
EXPERIMENT_ROOT = HERE.parents[1]
RESULTS_ROOT = EXPERIMENT_ROOT / "results"
INPUT_ROOT_NAME = "public_checkpoint_min_norm_v21_development_30_r2"
ATTEMPT_1_ROOT_NAME = "public_checkpoint_min_norm_v21_development_30"
DEFAULT_ROOT = RESULTS_ROOT / INPUT_ROOT_NAME
DEFAULT_OUTPUT = RESULTS_ROOT / f"{INPUT_ROOT_NAME}_paper"

SCHEMA_VERSION = "public_checkpoint_min_norm_v21_r2"
ARTIFACT_SCHEMA = "public_checkpoint_min_norm_v21_r2_descriptive_paper_v1"
DEVELOPMENT_SEEDS = tuple(range(41001, 41031))
K_VALUES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30, 40, 50)
HORIZONS = (30, 90, 180, 365)
FILTERED_TRAFFIC = "known_infrastructure_excluded"
ALL_ADDRESS_TRAFFIC = "all_addresses"
TRAFFIC_MODES = (FILTERED_TRAFFIC, ALL_ADDRESS_TRAFFIC)
RELEASE = "checkpoint_totals"
SEED_COUNT = len(DEVELOPMENT_SEEDS)

# This digest pins the closed r2 inventory. The generator streams every listed
# file only to authenticate its checksum; it never parses, decompresses, joins,
# or emits the private truth payloads. The presentation values themselves come
# exclusively from the whitelisted aggregate public provenance/summary files.
EXPECTED_ROOT_INVENTORY_SHA256 = "0a9112c876eb0479e64da2584c5f24aaeb6dd42642f6001b725f64eb0612b1ea"
EXPECTED_ROOT_CHECKSUM_ENTRIES = 159
EXPECTED = {
    "config_sha256": "51af281567d36741c273f717498581a0ff550a9fb019f0c3cac764bb907922c1",
    "semantic_config_sha256": "cd20f4cf6c8eccafb16b18f541e603ca8f415cc04228355fbd22a65a7c8e0826",
    "calibration_sha256": "6993bbf440904c24bc50bb2675c5ed9c3aa712ccaa0cfa59ef7610463dcb66ae",
    "dependency_lock_sha256": "d346b915c6b2931769abe883cac8117494b40b028ae2001b5b9bbb34eeb4983c",
    "reused_v2_modules_sha256": "9b9b450f0519ec4021299bfdca61ef5b3a5e4714fb205c217cd90c338c72fbeb",
    "solver_fingerprint": "bc09671a0efc88c18c69bcee6d82220f7c045d4ee59a4c2d68342f3e52aa0c01",
    "source_code_fingerprint": "34774d37371069e0a4753d165fb773b7f607ee9019d35757da819b266bcb79fe",
}
EXPECTED_PUBLIC_SOURCE_HASHES = {
    "executed_config.json": "ac7ebf50daec511827b26612939c47989936aa6dd4ab21577a95c6c2ccf8a6c8",
    "run_metadata.json": "1a0790ae91484fbf28cfbe5a2085fac169bdabd4642ec72a39dc5d67ed0c89ff",
    "source_files.json": "a4c0cdb2a84a1f2c717ec0514ebc1678ad21e5a6d5ed306160e016e242a76591",
    "public/summary/development_summary.csv": "9d3a490e9bac30bacb1d60bc079c5a87fa08d92d4900fef58b45c8d5c7816b9f",
    "public/summary/summary_metadata.json": "4afc3d3ee1bb6bee1a429aa8583d4823b4e49b5ad23a5cee106f7df1bf08acaa",
}
EXPECTED_SOURCE_FILES = {
    "src/leakage_attack/v21_config.py": "5cbe11af0c68a3b1956d86c6fc28c15f42768f856d7b17474bd6e3ce7661e117",
    "src/leakage_attack/v21_development.py": "504713e39fc4bdd412e2904e8139a47448b1e6a5ec6da6672ebe68b41e323509",
    "src/leakage_attack/v21_development_cli.py": "6b7fc9848ba101dd63eda738370817a21f625e6202bd46fd5cb7d52ea7fe5b29",
    "src/leakage_attack/v21_estimator.py": "9ff76f99f810824a8c683fa2bedd8c58748a0e43a23b4b5c33b50016ef952454",
    "src/leakage_attack/v21_evaluate.py": "bb3388977417fc50bbbe4ddbc1fb5ec7b3b150c83bc795b4cbd61570aaa0f320",
    "src/leakage_attack/v21_paths.py": "32d35189cc3dd0c5d8f10a59dcf1c4d729a7554c71badd1d8fdcedf28a117f8b",
    "src/leakage_attack/v21_simulate.py": "2d456c57bfa2b35da9430c6577082e98283eaa3302781a5b3cadcad66d6c7309",
    "src/leakage_attack/v21_summarize.py": "7a19c9436f0fd3552bfc070de2b4525ae24ca6e64a32ff5c6efadcdd80c92b21",
}
EXPECTED_REUSED_V2_FILES = {
    "src/leakage_attack/v2_calibration.py": "a62e33274d245e5a4872089e1e771d3838cf8f26026bc0da03d20a45987a8da2",
    "src/leakage_attack/v2_config.py": "6d5295deb8c8db79c292b369725ebf127d1c2149c3e620810d46b28d86faa082",
    "src/leakage_attack/v2_disclosure.py": "cbd8a160798b00d51d2877c7b30908b95bf18a481932e0361c79db59550827ce",
    "src/leakage_attack/v2_simulator.py": "3accb617e63d99d07a2adab0b258ac0406e1fe74319648d0e397237d34765534",
}

SUMMARY_COLUMNS = (
    "traffic_mode", "k", "horizon_day", "metric", "n_seed_cells", "n_successful", "n_failed", "mean",
)
SUMMARY_METRICS = (
    "position_within_10pct",
    "completed_operation_within_10pct",
    "tail_operation_within_10pct",
    "all_operation_within_10pct",
    "solver_runtime_seconds",
    "tail_action_rate",
    "solver_failure_fraction",
)
RESULTS_SOURCE_COLUMNS = (
    "k",
    "filtered_active_position_p10_day365",
    "filtered_completed_operation_p10_day365",
    "all_addresses_active_position_p10_day365",
    "all_addresses_completed_operation_p10_day365",
    "n_seeds",
)
HORIZON_TAIL_SOURCE_COLUMNS = (
    "panel", "traffic_mode", "k", "horizon_day", "metric", "mean", "n_seeds",
)
FIGURE_DIMENSIONS = {
    "v21_reconstruction_outcomes": (1500, 1500),
    "v21_horizon_tail": (1500, 1850),
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class ValidatedInputs:
    """Authenticated aggregate-only paper inputs held in memory."""

    root: Path
    summary_rows: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any]
    source_manifest: Mapping[str, Any]
    executed_config: Mapping[str, Any]
    summary_metadata: Mapping[str, Any]
    inventory_sha256: str
    public_source_sha256: Mapping[str, str]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to read public JSON source: {path.name}") from error
    require(isinstance(payload, dict), f"public JSON source must be an object: {path.name}")
    return payload


def _absolute(path: str | Path) -> Path:
    raw = Path(path).expanduser()
    return raw if raw.is_absolute() else Path.cwd() / raw


def _assert_regular_non_symlink(path: Path, *, label: str) -> None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing: {path}") from error
    require(not stat.S_ISLNK(metadata.st_mode), f"{label} must not be a symlink: {path}")
    require(stat.S_ISREG(metadata.st_mode), f"{label} must be a regular file: {path}")


def _assert_directory_non_symlink(path: Path, *, label: str) -> None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing: {path}") from error
    require(not stat.S_ISLNK(metadata.st_mode), f"{label} must not be a symlink: {path}")
    require(stat.S_ISDIR(metadata.st_mode), f"{label} must be a directory: {path}")


def _all_regular_files(root: Path) -> set[str]:
    """List a closed tree while refusing symlinks without opening file payloads."""

    output: set[str] = set()
    for directory, directories, names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in directories:
            candidate = directory_path / name
            metadata = os.lstat(candidate)
            require(not stat.S_ISLNK(metadata.st_mode), f"input root contains a symlink: {candidate}")
            require(stat.S_ISDIR(metadata.st_mode), f"input root has a non-directory component: {candidate}")
        for name in names:
            candidate = directory_path / name
            metadata = os.lstat(candidate)
            require(not stat.S_ISLNK(metadata.st_mode), f"input root contains a symlink: {candidate}")
            require(stat.S_ISREG(metadata.st_mode), f"input root contains a non-regular file: {candidate}")
            output.add(candidate.relative_to(root).as_posix())
    return output


def _parse_checksum_inventory(root: Path) -> dict[str, str]:
    inventory = root / "SHA256SUMS"
    _assert_regular_non_symlink(inventory, label="r2 checksum inventory")
    inventory_sha = sha256(inventory)
    require(inventory_sha == EXPECTED_ROOT_INVENTORY_SHA256, "r2 checksum inventory fingerprint mismatch")
    entries: dict[str, str] = {}
    for line in inventory.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as error:
            raise ValueError("invalid r2 checksum inventory entry") from error
        candidate = Path(relative)
        require(
            len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
            and not candidate.is_absolute()
            and ".." not in candidate.parts
            and relative not in entries,
            "unsafe r2 checksum inventory entry",
        )
        entries[relative] = digest
    require(len(entries) == EXPECTED_ROOT_CHECKSUM_ENTRIES, "unexpected r2 checksum inventory size")
    actual = _all_regular_files(root) - {"SHA256SUMS"}
    require(set(entries) == actual, "r2 checksum inventory is incomplete")
    # Authenticate the complete closed root, including the evaluator-only
    # files, by streaming SHA-256 only. No private payload is parsed,
    # decompressed, retained, or used to compute a paper value.
    for relative, expected in entries.items():
        source = root / relative
        _assert_regular_non_symlink(source, label="r2 checksum source")
        require(sha256(source) == expected, f"r2 checksum mismatch: {relative}")
    for relative, expected in EXPECTED_PUBLIC_SOURCE_HASHES.items():
        require(entries.get(relative) == expected, f"r2 public source inventory mismatch: {relative}")
    return entries


def _reject_forbidden_claim_fields(value: Any, *, path: str = "") -> None:
    """Reject active selection/qualification/confirmation metadata fields.

    Explicit negative prose is allowed in values; only semantic field names
    would create an active decision or inferential result in the source schema.
    """

    forbidden = ("selected", "selection", "qualif", "ucb", "confidence", "confirmatory", "confirmation")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            require(isinstance(key, str), f"non-string metadata field at {path or '<root>'}")
            lowered = key.lower()
            require(not any(token in lowered for token in forbidden), f"forbidden decision/inference field: {path}/{key}")
            _reject_forbidden_claim_fields(nested, path=f"{path}/{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_claim_fields(nested, path=f"{path}/{index}")


def assert_public_summary_fields(fields: Sequence[str]) -> None:
    """Fail closed if a development summary exposes private or non-summary fields."""

    require(tuple(fields) == SUMMARY_COLUMNS, "unexpected public development-summary schema")
    forbidden = ("truth", "private", "hidden", "action_id", "eligible_id", "position_value", "amount")
    for field in fields:
        require(not any(token in field.lower() for token in forbidden), "private field in paper input summary")
        require(not any(token in field.lower() for token in ("selected", "selection", "qualif", "ucb", "confidence", "confirm")), "forbidden decision/inference field in paper input summary")


def _parse_int(value: str, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid integer public-summary field: {field}") from error
    require(str(parsed) == value, f"non-canonical integer public-summary field: {field}")
    return parsed


def _parse_finite(value: str, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid numeric public-summary field: {field}") from error
    require(math.isfinite(parsed), f"non-finite public-summary field: {field}")
    return parsed


def _read_and_validate_summary(path: Path) -> tuple[Mapping[str, Any], ...]:
    _assert_regular_non_symlink(path, label="public development summary")
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(reader.fieldnames or ())
            assert_public_summary_fields(fields)
            raw_rows = list(reader)
    except OSError as error:
        raise ValueError("unable to read public development summary") from error
    expected = {
        (traffic, k, horizon, metric)
        for traffic in TRAFFIC_MODES
        for k in K_VALUES
        for horizon in HORIZONS
        for metric in SUMMARY_METRICS
    }
    require(len(raw_rows) == len(expected), "public development summary row count mismatch")
    output: list[Mapping[str, Any]] = []
    observed: set[tuple[str, int, int, str]] = set()
    bounded_metrics = {
        "position_within_10pct",
        "completed_operation_within_10pct",
        "tail_operation_within_10pct",
        "all_operation_within_10pct",
        "tail_action_rate",
        "solver_failure_fraction",
    }
    for row in raw_rows:
        require(set(row) == set(SUMMARY_COLUMNS), "public development summary carries an unexpected field")
        traffic = row["traffic_mode"]
        k = _parse_int(row["k"], field="k")
        horizon = _parse_int(row["horizon_day"], field="horizon_day")
        metric = row["metric"]
        key = (traffic, k, horizon, metric)
        require(key in expected and key not in observed, "public development summary has an invalid or duplicate cell")
        observed.add(key)
        n_cells = _parse_int(row["n_seed_cells"], field="n_seed_cells")
        n_successful = _parse_int(row["n_successful"], field="n_successful")
        n_failed = _parse_int(row["n_failed"], field="n_failed")
        require((n_cells, n_successful, n_failed) == (SEED_COUNT, SEED_COUNT, 0), "paper input contains a missing or failed development cell")
        value = _parse_finite(row["mean"], field="mean")
        require(value >= 0.0, "public development summary contains a negative mean")
        if metric in bounded_metrics:
            require(value <= 1.0, "bounded public development mean exceeds one")
        if metric == "solver_failure_fraction":
            require(value == 0.0, "paper input contains a solver failure fraction")
        output.append({
            "traffic_mode": traffic,
            "k": k,
            "horizon_day": horizon,
            "metric": metric,
            "n_seed_cells": n_cells,
            "n_successful": n_successful,
            "n_failed": n_failed,
            "mean": value,
        })
    require(observed == expected, "public development summary matrix is incomplete")
    return tuple(output)


def _require_exact_domain(metadata: Mapping[str, Any], executed: Mapping[str, Any], summary: Mapping[str, Any]) -> None:
    _reject_forbidden_claim_fields(metadata)
    _reject_forbidden_claim_fields(executed)
    _reject_forbidden_claim_fields(summary)
    require(metadata.get("schema_version") == SCHEMA_VERSION, "r2 schema mismatch")
    require(metadata.get("phase") == "development", "r2 phase is not development")
    require(metadata.get("complete_development_domain") is True, "r2 is not a complete development domain")
    require(metadata.get("configured_development_seed_range") == [DEVELOPMENT_SEEDS[0], DEVELOPMENT_SEEDS[-1]], "r2 development seed range mismatch")
    require(metadata.get("seeds") == list(DEVELOPMENT_SEEDS), "r2 seed domain mismatch")
    require(metadata.get("cells_per_seed") == 120, "r2 cells-per-seed mismatch")
    require(metadata.get("release") == RELEASE, "r2 release mismatch")
    provenance = metadata.get("provenance")
    require(isinstance(provenance, Mapping), "r2 provenance is missing")
    require(dict(provenance) == EXPECTED, "r2 provenance fingerprint mismatch")
    layout = metadata.get("public_private_layout")
    require(
        layout == {
            "public": "metrics, numerical diagnostics, and public action estimates only",
            "private": "truth joins used only after sealed public estimation",
        },
        "r2 public/private layout mismatch",
    )
    embedded = metadata.get("summary")
    require(isinstance(embedded, Mapping), "r2 summary metadata is missing")
    require(embedded.get("external_safe") is True and embedded.get("contains_private_operation_rows") is False, "r2 summary is not external safe")
    require(embedded.get("schema_version") == SCHEMA_VERSION and embedded.get("phase") == "development", "r2 embedded summary domain mismatch")
    require(embedded.get("seeds") == list(DEVELOPMENT_SEEDS), "r2 embedded summary seed domain mismatch")
    require(embedded.get("outputs") == {"development_summary_rows": 840}, "r2 embedded summary output mismatch")

    require(executed.get("schema_version") == SCHEMA_VERSION, "executed r2 schema mismatch")
    require(executed.get("evidence_status") == "development_only_nonconfirmatory", "executed r2 status mismatch")
    require(executed.get("canonical_development_output_root") == f"results/{INPUT_ROOT_NAME}", "executed r2 root mismatch")
    require(executed.get("development_seed_range") == [DEVELOPMENT_SEEDS[0], DEVELOPMENT_SEEDS[-1]], "executed r2 seed range mismatch")
    require(executed.get("k_values") == list(K_VALUES), "executed r2 k grid mismatch")
    require(executed.get("horizons") == list(HORIZONS), "executed r2 horizon domain mismatch")
    require(executed.get("traffic_modes") == list(TRAFFIC_MODES), "executed r2 traffic domain mismatch")
    require(executed.get("release") == RELEASE, "executed r2 release mismatch")
    require(executed.get("calibration_artifact_sha256") == EXPECTED["calibration_sha256"], "executed r2 calibration binding mismatch")
    attacker = executed.get("attacker")
    require(isinstance(attacker, Mapping), "executed r2 attacker declaration is missing")
    require(attacker.get("magnitude_domain") == "continuous_nonnegative_microshares", "executed r2 magnitude domain mismatch")
    require(attacker.get("ignored_public_fields") == ["rate", "checkpoint_assets"], "executed r2 public-input boundary mismatch")
    require("qualification selection" in executed.get("prohibited", []) and "confidence-bound qualification" in executed.get("prohibited", []), "executed r2 does not prohibit decision logic")

    expected_summary_fields = {
        "contains_private_operation_rows", "description", "external_safe", "independent_unit", "outputs", "phase", "schema_version", "seeds",
    }
    require(set(summary) == expected_summary_fields, "public summary metadata schema mismatch")
    require(summary.get("schema_version") == SCHEMA_VERSION and summary.get("phase") == "development", "public summary metadata domain mismatch")
    require(summary.get("seeds") == list(DEVELOPMENT_SEEDS), "public summary metadata seed domain mismatch")
    require(summary.get("outputs") == {"development_summary_rows": 840}, "public summary output count mismatch")
    require(summary.get("external_safe") is True and summary.get("contains_private_operation_rows") is False, "public summary metadata exposes private rows")
    require(summary.get("independent_unit") == "complete synthetic seed trace", "public summary independent-unit mismatch")


def _validate_source_manifest(source_manifest: Mapping[str, Any]) -> None:
    _reject_forbidden_claim_fields(source_manifest)
    require(source_manifest.get("schema_version") == SCHEMA_VERSION, "r2 source-manifest schema mismatch")
    require(source_manifest.get("source_scope") == "v21_python_only", "r2 source-manifest scope mismatch")
    v21_files = source_manifest.get("v21_files")
    reused = source_manifest.get("reused_unchanged_v2_modules")
    require(isinstance(v21_files, list) and isinstance(reused, list), "r2 source-manifest file lists are missing")
    parsed_v21 = {entry.get("path"): entry.get("sha256") for entry in v21_files if isinstance(entry, Mapping)}
    parsed_reused = {entry.get("path"): entry.get("sha256") for entry in reused if isinstance(entry, Mapping)}
    require(parsed_v21 == EXPECTED_SOURCE_FILES, "r2 v2.1 source fingerprint file set mismatch")
    require(parsed_reused == EXPECTED_REUSED_V2_FILES, "r2 reused-v2 source fingerprint file set mismatch")


def validate_inputs(root: str | Path = DEFAULT_ROOT) -> ValidatedInputs:
    """Authenticate the one complete r2 root using public summary material only."""

    candidate = _absolute(root)
    _assert_directory_non_symlink(candidate, label="V2.1 paper input root")
    require(candidate.name == INPUT_ROOT_NAME, "V2.1 paper generator accepts only the corrected r2 root, never attempt 1")
    inventory = _parse_checksum_inventory(candidate)
    metadata = read_json(candidate / "run_metadata.json")
    source_manifest = read_json(candidate / "source_files.json")
    executed = read_json(candidate / "executed_config.json")
    summary_metadata = read_json(candidate / "public" / "summary" / "summary_metadata.json")
    _require_exact_domain(metadata, executed, summary_metadata)
    _validate_source_manifest(source_manifest)
    rows = _read_and_validate_summary(candidate / "public" / "summary" / "development_summary.csv")
    # The r2 inventory has exactly the canonical provenance rows; bind each
    # source's read digest back to it after schema validation as well.
    source_hashes = {relative: sha256(candidate / relative) for relative in EXPECTED_PUBLIC_SOURCE_HASHES}
    require(source_hashes == EXPECTED_PUBLIC_SOURCE_HASHES, "public source fingerprint changed during validation")
    require(all(inventory[relative] == digest for relative, digest in source_hashes.items()), "public source inventory changed during validation")
    return ValidatedInputs(
        root=candidate.resolve(), summary_rows=rows, metadata=metadata, source_manifest=source_manifest,
        executed_config=executed, summary_metadata=summary_metadata,
        inventory_sha256=EXPECTED_ROOT_INVENTORY_SHA256, public_source_sha256=source_hashes,
    )


def _lookup(rows: Sequence[Mapping[str, Any]], traffic: str, k: int, horizon: int, metric: str) -> Mapping[str, Any]:
    matches = [
        row for row in rows
        if row["traffic_mode"] == traffic and int(row["k"]) == k
        and int(row["horizon_day"]) == horizon and row["metric"] == metric
    ]
    require(len(matches) == 1, f"missing authenticated summary cell: {traffic}/k={k}/day={horizon}/{metric}")
    return matches[0]


def build_results_source(inputs: ValidatedInputs) -> list[dict[str, Any]]:
    """Create the sole 15-row source for the descriptive table and outcome figure."""

    output: list[dict[str, Any]] = []
    for k in K_VALUES:
        output.append({
            "k": k,
            "filtered_active_position_p10_day365": _lookup(inputs.summary_rows, FILTERED_TRAFFIC, k, 365, "position_within_10pct")["mean"],
            "filtered_completed_operation_p10_day365": _lookup(inputs.summary_rows, FILTERED_TRAFFIC, k, 365, "completed_operation_within_10pct")["mean"],
            "all_addresses_active_position_p10_day365": _lookup(inputs.summary_rows, ALL_ADDRESS_TRAFFIC, k, 365, "position_within_10pct")["mean"],
            "all_addresses_completed_operation_p10_day365": _lookup(inputs.summary_rows, ALL_ADDRESS_TRAFFIC, k, 365, "completed_operation_within_10pct")["mean"],
            "n_seeds": SEED_COUNT,
        })
    require(len(output) == len(K_VALUES) and [row["k"] for row in output] == list(K_VALUES), "descriptive table source must contain exactly the tested grid")
    return output


def build_horizon_tail_source(inputs: ValidatedInputs) -> list[dict[str, Any]]:
    """Create the source for filtered P10 horizons and both-mode day-365 tails."""

    output: list[dict[str, Any]] = []
    for k in K_VALUES:
        for horizon in HORIZONS:
            output.append({
                "panel": "filtered_active_position_p10_by_horizon",
                "traffic_mode": FILTERED_TRAFFIC,
                "k": k,
                "horizon_day": horizon,
                "metric": "active_position_p10",
                "mean": _lookup(inputs.summary_rows, FILTERED_TRAFFIC, k, horizon, "position_within_10pct")["mean"],
                "n_seeds": SEED_COUNT,
            })
        for traffic in TRAFFIC_MODES:
            output.append({
                "panel": "day365_tail_fraction_by_traffic",
                "traffic_mode": traffic,
                "k": k,
                "horizon_day": 365,
                "metric": "tail_fraction",
                "mean": _lookup(inputs.summary_rows, traffic, k, 365, "tail_action_rate")["mean"],
                "n_seeds": SEED_COUNT,
            })
    require(len(output) == len(K_VALUES) * (len(HORIZONS) + len(TRAFFIC_MODES)), "horizon/tail source row count mismatch")
    return output


def _csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return format(value, ".17g")
    return value


def write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        for row in rows:
            require(tuple(row) == tuple(columns), "generated source CSV schema mismatch")
            writer.writerow({key: _csv_value(value) for key, value in row.items()})


# --- Minimal deterministic editable SVG rendering ---------------------------------

def svg_document(width: int, height: int, title: str, body: Sequence[str]) -> str:
    return "\n".join((
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#172033}.title{font-size:48px;font-weight:700}.sub{font-size:34px;fill:#475569}.label{font-size:38px;font-weight:600}.tick{font-size:32px;fill:#475569}.tiny{font-size:32px;fill:#475569}.note{font-size:32px;font-weight:600;fill:#1d4ed8}</style>',
        *body,
        '</svg>',
        '',
    ))


def svg_text(x: float, y: float, value: str, css: str = "label", anchor: str = "start", rotate: float | None = None) -> str:
    transform = "" if rotate is None else f' transform="rotate({rotate:.1f} {x:.1f} {y:.1f})"'
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{css}" text-anchor="{anchor}"{transform}>{html.escape(value)}</text>'


def svg_line(x1: float, y1: float, x2: float, y2: float, color: str = "#334155", width: float = 1.0, dash: str = "") -> str:
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width:.1f}"{dashed}/>'


def svg_circle(x: float, y: float, color: str, radius: float = 7.0, fill: str | None = None) -> str:
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{fill or color}" stroke="{color}" stroke-width="1.5"/>'


def svg_square(x: float, y: float, color: str, radius: float = 7.0, fill: str | None = None) -> str:
    return f'<rect x="{x-radius:.1f}" y="{y-radius:.1f}" width="{2*radius:.1f}" height="{2*radius:.1f}" fill="{fill or color}" stroke="{color}" stroke-width="1.5"/>'


def svg_triangle(x: float, y: float, color: str, radius: float = 8.0, fill: str | None = None) -> str:
    points = f"{x:.1f},{y-radius:.1f} {x-radius:.1f},{y+radius:.1f} {x+radius:.1f},{y+radius:.1f}"
    return f'<polygon points="{points}" fill="{fill or color}" stroke="{color}" stroke-width="1.4"/>'


def scaled_y(value: float, y0: float, height: float, maximum: float) -> float:
    return y0 + height - height * min(max(value, 0.0), maximum) / maximum


def categorical_x(index: int, count: int, x0: float, width: float) -> float:
    return x0 + 58 + index * (width - 116) / (count - 1)


def plot_axes(
    body: list[str], *, x0: float, y0: float, width: float, height: float,
    y_ticks: Sequence[float], y_max: float, title: str, y_label: str,
) -> None:
    body.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{width:.1f}" height="{height:.1f}" fill="#f8fafc" stroke="#cbd5e1"/>')
    body.append(svg_text(x0 + width / 2, y0 - 28, title, "label", "middle"))
    for tick in y_ticks:
        y = scaled_y(tick, y0, height, y_max)
        body.extend((svg_line(x0, y, x0 + width, y, "#e2e8f0", 1.5), svg_text(x0 - 16, y + 11, f"{tick:g}%", "tick", "end")))
    body.append(svg_text(x0 - 82, y0 + height / 2, y_label, "tiny", "middle", -90))


def categorical_axis(body: list[str], *, x0: float, y0: float, width: float, height: float) -> dict[int, float]:
    positions = {k: categorical_x(index, len(K_VALUES), x0, width) for index, k in enumerate(K_VALUES)}
    for k, x in positions.items():
        body.extend((svg_line(x, y0 + height, x, y0 + height + 8, width=1.5), svg_text(x, y0 + height + 42, str(k), "tick", "middle")))
    body.append(svg_text(x0 + width / 2, y0 + height + 92, "distinct eligible pseudonyms k (tested categories)", "tiny", "middle"))
    return positions


def _source_value(row: Mapping[str, Any], column: str) -> float:
    value = row[column]
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"invalid figure source field: {column}")
    return float(value)


def reconstruction_figure(source: Sequence[Mapping[str, Any]], output: Path) -> tuple[str, int, int]:
    stem = "v21_reconstruction_outcomes"
    width, height = FIGURE_DIMENSIONS[stem]
    body: list[str] = [
        svg_text(width / 2, 60, "V2.1 reconstruction outcomes by traffic mode", "title", "middle"),
        svg_text(width / 2, 108, "30-seed development-only descriptive means; categorical tested k values", "sub", "middle"),
    ]
    panels = (
        (FILTERED_TRAFFIC, "A. Filtered traffic", 190),
        (ALL_ADDRESS_TRAFFIC, "B. All-address traffic", 865),
    )
    column = {
        FILTERED_TRAFFIC: ("filtered_active_position_p10_day365", "filtered_completed_operation_p10_day365"),
        ALL_ADDRESS_TRAFFIC: ("all_addresses_active_position_p10_day365", "all_addresses_completed_operation_p10_day365"),
    }
    styles = (
        ("active-position P10", "#1d4ed8", "circle"),
        ("completed-operation P10", "#b45309", "square"),
    )
    x0, plot_width, plot_height, y_max = 155, 1270, 360, 25.0
    for traffic, title, y0 in panels:
        plot_axes(body, x0=x0, y0=y0, width=plot_width, height=plot_height, y_ticks=(0, 5, 10, 15, 20, 25), y_max=y_max, title=title, y_label="P10 (%)")
        positions = categorical_axis(body, x0=x0, y0=y0, width=plot_width, height=plot_height)
        for (label, color, marker), source_column in zip(styles, column[traffic], strict=True):
            for row in source:
                k = int(row["k"])
                value = 100.0 * _source_value(row, source_column)
                x = positions[k]
                if value > y_max:
                    # The known k=1 value is retained as an explicit capped
                    # category marker instead of silently clipped or joined.
                    if marker == "circle":
                        body.append(svg_triangle(x - 6, y0 + 10, color, 8.0, "#ffffff"))
                    else:
                        body.append(svg_triangle(x + 6, y0 + 10, color, 8.0, "#ffffff"))
                elif marker == "circle":
                    body.append(svg_circle(x - 5, scaled_y(value, y0, plot_height, y_max), color, 7.0))
                else:
                    body.append(svg_square(x + 5, scaled_y(value, y0, plot_height, y_max), color, 7.0))
            legend_y = y0 + plot_height + 152
            index = 0 if marker == "circle" else 1
            lx = x0 + 330 + index * 440
            if marker == "circle":
                body.append(svg_circle(lx, legend_y, color, 7.0))
            else:
                body.append(svg_square(lx, legend_y, color, 7.0))
            body.append(svg_text(lx + 30, legend_y + 11, label, "tiny"))
        body.append(svg_text(positions[1] + 36, y0 + 41, "k=1: both values are 100% (off scale)", "note"))
    body.extend((
        svg_text(width / 2, 1412, "Marks are descriptive category means; no smoothing or interpolation is implied.", "sub", "middle"),
        svg_text(width / 2, 1454, "P10 is the fraction within 10% relative error; operations use completed-window share flow.", "sub", "middle"),
    ))
    return save_figure(stem, svg_document(width, height, "V2.1 reconstruction outcomes", body), output)


def _heat_colour(value: float) -> str:
    """A small deterministic white-to-blue sequential palette for P10 cells."""

    fraction = min(max(value, 0.0), 1.0)
    low, high = (239, 246, 255), (30, 64, 175)
    channels = tuple(round(low[index] + fraction * (high[index] - low[index])) for index in range(3))
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def horizon_tail_figure(source: Sequence[Mapping[str, Any]], output: Path) -> tuple[str, int, int]:
    stem = "v21_horizon_tail"
    width, height = FIGURE_DIMENSIONS[stem]
    body: list[str] = [
        svg_text(width / 2, 60, "V2.1 horizons and unreleased-tail behavior", "title", "middle"),
        svg_text(width / 2, 108, "30-seed development-only descriptive means; no threshold or interval analysis", "sub", "middle"),
    ]

    # Panel A: all filtered k/horizon values are visible without privileging a
    # subset of categories.  It is a categorical matrix, not an interpolated curve.
    x0, y0, cell_w, cell_h = 345, 230, 230, 45
    body.append(svg_text(width / 2, 175, "A. Filtered-traffic active-position P10 across horizons", "label", "middle"))
    active = {
        (int(row["k"]), int(row["horizon_day"])): _source_value(row, "mean")
        for row in source if row["panel"] == "filtered_active_position_p10_by_horizon"
    }
    require(len(active) == len(K_VALUES) * len(HORIZONS), "horizon figure source lacks filtered active-position cells")
    for index, horizon in enumerate(HORIZONS):
        body.append(svg_text(x0 + index * cell_w + cell_w / 2, y0 - 18, f"day {horizon}", "tick", "middle"))
    for row_index, k in enumerate(K_VALUES):
        y = y0 + row_index * cell_h
        body.append(svg_text(x0 - 20, y + 34, f"k={k}", "tick", "end"))
        for column_index, horizon in enumerate(HORIZONS):
            value = active[(k, horizon)]
            x = x0 + column_index * cell_w
            body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="{cell_h:.1f}" fill="{_heat_colour(value)}" stroke="#ffffff" stroke-width="2"/>')
    body.append(svg_text(x0 - 105, y0 + len(K_VALUES) * cell_h / 2, "tested category", "tiny", "middle", -90))
    legend_y = y0 + len(K_VALUES) * cell_h + 72
    for index, fraction in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
        lx = x0 + index * 180
        body.append(f'<rect x="{lx:.1f}" y="{legend_y:.1f}" width="60" height="30" fill="{_heat_colour(fraction)}" stroke="#cbd5e1"/>')
        body.append(svg_text(lx + 72, legend_y + 25, f"{100*fraction:.0f}%", "tiny"))
    body.append(svg_text(x0 + 450, legend_y + 74, "cell colour: active-position P10", "tiny", "middle"))

    # Panel B: both traffic modes share one categorical tail-rate panel.
    tail = {
        (row["traffic_mode"], int(row["k"])): _source_value(row, "mean")
        for row in source if row["panel"] == "day365_tail_fraction_by_traffic"
    }
    require(len(tail) == len(TRAFFIC_MODES) * len(K_VALUES), "horizon figure source lacks day-365 tail cells")
    max_tail_pct = 100.0 * max(tail.values())
    y_max = max(5.0, math.ceil(max_tail_pct / 5.0) * 5.0)
    if y_max > 25.0:
        y_max = math.ceil(max_tail_pct / 10.0) * 10.0
    ticks = tuple(float(value) for value in range(0, int(y_max) + 1, 5 if y_max <= 25 else 10))
    plot_x, plot_y, plot_width, plot_height = 155, 1143, 1270, 300
    plot_axes(body, x0=plot_x, y0=plot_y, width=plot_width, height=plot_height, y_ticks=ticks, y_max=y_max, title="B. Day-365 unreleased-tail fraction", y_label="tail fraction (%)")
    positions = categorical_axis(body, x0=plot_x, y0=plot_y, width=plot_width, height=plot_height)
    traffic_style = (
        (FILTERED_TRAFFIC, "#0f766e", "circle", "filtered traffic"),
        (ALL_ADDRESS_TRAFFIC, "#7c3aed", "square", "all-address traffic"),
    )
    for index, (traffic, color, marker, label) in enumerate(traffic_style):
        for k in K_VALUES:
            x = positions[k] + (-5 if marker == "circle" else 5)
            y = scaled_y(100.0 * tail[(traffic, k)], plot_y, plot_height, y_max)
            body.append(svg_circle(x, y, color, 7.0) if marker == "circle" else svg_square(x, y, color, 7.0))
        lx, ly = plot_x + 330 + index * 470, plot_y + plot_height + 152
        body.append(svg_circle(lx, ly, color, 7.0) if marker == "circle" else svg_square(lx, ly, color, 7.0))
        body.append(svg_text(lx + 30, ly + 11, label, "tiny"))
    body.extend((
        svg_text(width / 2, 1712, "Tail fraction is the mean share of visible actions after the final released checkpoint at day 365.", "sub", "middle"),
        svg_text(width / 2, 1754, "All marks and cells are categorical descriptive means; no smoothing or interpolation is implied.", "sub", "middle"),
    ))
    return save_figure(stem, svg_document(width, height, "V2.1 horizons and tail behavior", body), output)


# --- Deterministic opaque RGB PNG conversion ---------------------------------------

def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    require(data.startswith(PNG_SIGNATURE), "not a PNG")
    output: list[tuple[bytes, bytes]] = []
    position = len(PNG_SIGNATURE)
    while position < len(data):
        require(position + 12 <= len(data), "truncated PNG chunk")
        size = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        end = position + 12 + size
        require(end <= len(data), "truncated PNG payload")
        payload = data[position + 8:position + 8 + size]
        output.append((kind, payload))
        position = end
        if kind == b"IEND":
            break
    require(output and output[-1][0] == b"IEND" and position == len(data), "malformed PNG termination")
    return output


def unfilter_png(raw: bytes, width: int, height: int, bpp: int) -> list[bytearray]:
    stride = width * bpp
    require(len(raw) == height * (stride + 1), "unexpected PNG buffer size")
    rows: list[bytearray] = []
    position = 0
    for _ in range(height):
        method = raw[position]
        position += 1
        row = bytearray(raw[position:position + stride])
        position += stride
        prior = rows[-1] if rows else bytearray(stride)
        for index in range(stride):
            left = row[index - bpp] if index >= bpp else 0
            up = prior[index]
            upper_left = prior[index - bpp] if index >= bpp else 0
            if method == 0:
                value = row[index]
            elif method == 1:
                value = row[index] + left
            elif method == 2:
                value = row[index] + up
            elif method == 3:
                value = row[index] + (left + up) // 2
            elif method == 4:
                estimate = left + up - upper_left
                choices = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
                predictor = left if choices[0] <= choices[1] and choices[0] <= choices[2] else up if choices[1] <= choices[2] else upper_left
                value = row[index] + predictor
            else:
                raise ValueError("unsupported PNG filter")
            row[index] = value & 255
        rows.append(row)
    return rows


def write_rgb_png(path: Path, width: int, height: int, rows: Sequence[bytearray]) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    require(len(rows) == height and all(len(row) == width * 3 for row in rows), "invalid RGB PNG rows")
    raw = b"".join(b"\0" + bytes(row) for row in rows)
    path.write_bytes(
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def normalize_png(path: Path) -> dict[str, Any]:
    chunks = png_chunks(path.read_bytes())
    header = next((payload for kind, payload in chunks if kind == b"IHDR"), None)
    require(header is not None, "PNG lacks IHDR")
    width, height, depth, colour_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", header)
    require((depth, compression, filtering, interlace) == (8, 0, 0, 0) and colour_type in (2, 6), "unsupported PNG encoding")
    bpp = 4 if colour_type == 6 else 3
    compressed = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    rows = unfilter_png(zlib.decompress(compressed), width, height, bpp)
    if colour_type == 6:
        rgb_rows: list[bytearray] = []
        for row in rows:
            destination = bytearray()
            for index in range(0, len(row), 4):
                red, green, blue, alpha = row[index:index + 4]
                destination.extend((
                    (red * alpha + 255 * (255 - alpha) + 127) // 255,
                    (green * alpha + 255 * (255 - alpha) + 127) // 255,
                    (blue * alpha + 255 * (255 - alpha) + 127) // 255,
                ))
            rgb_rows.append(destination)
        rows = rgb_rows
    write_rgb_png(path, width, height, rows)
    corners = [tuple(rows[y][3 * x:3 * x + 3]) for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))]
    require(all(pixel == (255, 255, 255) for pixel in corners), "PNG corners must be opaque white")
    return {"width": width, "height": height, "colour_type": "RGB", "has_alpha": False, "corner_pixels": corners}


def inspect_png(path: Path) -> dict[str, Any]:
    """Read and validate a generated PNG without changing it."""

    chunks = png_chunks(path.read_bytes())
    header = next((payload for kind, payload in chunks if kind == b"IHDR"), None)
    require(header is not None, "PNG lacks IHDR")
    width, height, depth, colour_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", header)
    require((depth, compression, filtering, interlace, colour_type) == (8, 0, 0, 0, 2), "PNG must be normalized opaque RGB")
    rows = unfilter_png(zlib.decompress(b"".join(payload for kind, payload in chunks if kind == b"IDAT")), width, height, 3)
    corners = [tuple(rows[y][3 * x:3 * x + 3]) for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))]
    require(all(pixel == (255, 255, 255) for pixel in corners), "PNG corners must be opaque white")
    return {"width": width, "height": height, "colour_type": "RGB", "has_alpha": False, "corner_pixels": corners}


def save_figure(stem: str, svg: str, output: Path) -> tuple[str, int, int]:
    svg_path = output / f"{stem}.svg"
    png_path = output / f"{stem}.png"
    svg_path.write_text(svg, encoding="utf-8")
    raster = subprocess.run(
        ["sips", "-s", "format", "png", str(svg_path), "--out", str(png_path)],
        capture_output=True,
        text=True,
    )
    require(raster.returncode == 0 and png_path.exists() and png_path.stat().st_size > 1_000, f"SVG rasterization failed: {raster.stderr.strip()}")
    info = normalize_png(png_path)
    expected_width, expected_height = FIGURE_DIMENSIONS[stem]
    require((info["width"], info["height"]) == (expected_width, expected_height), "generated figure dimensions mismatch")
    return stem, expected_width, expected_height


# --- Publication text and exclusively published bundle -----------------------------

def tex_pct(value: float, digits: int = 2) -> str:
    return f"{100 * value:.{digits}f}\\%"


def markdown_pct(value: float, digits: int = 3) -> str:
    return f"{100 * value:.{digits}f}%"


def _tex_escape(value: str) -> str:
    return value.replace("_", "\\_")


def descriptive_table(source: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "% Generated from the authenticated V2.1 r2 public development summary; requires booktabs.",
        "\\begin{table}[t]",
        "\\centering",
        "\\footnotesize",
        "\\setlength{\\tabcolsep}{3.1pt}",
        "\\begin{tabular}{@{}r r r r r@{}}",
        "\\toprule",
        "$k$ & \\shortstack{Filtered\\\\active-position P10} & \\shortstack{Filtered\\\\completed-operation P10} & \\shortstack{All-address\\\\active-position P10} & \\shortstack{All-address\\\\completed-operation P10} " + r"\\",
        "\\midrule",
    ]
    for row in source:
        lines.append(
            f"{int(row['k'])} & {tex_pct(_source_value(row, 'filtered_active_position_p10_day365'))} & "
            f"{tex_pct(_source_value(row, 'filtered_completed_operation_p10_day365'))} & "
            f"{tex_pct(_source_value(row, 'all_addresses_active_position_p10_day365'))} & "
            f"{tex_pct(_source_value(row, 'all_addresses_completed_operation_p10_day365'))} " + r"\\"
        )
    lines.extend((
        "\\bottomrule",
        "\\end{tabular}",
        "\\caption{Day-365 P10 descriptive means from 30 V2.1 development seed traces. Filtered traffic excludes known infrastructure; all-address traffic is a sensitivity. The specified public checkpoint minimum-norm heuristic uses completed-operation share flow. This table reports no threshold selection or confirmation.}",
        "\\label{tab:v21-descriptive-results}",
        "\\end{table}",
        "",
    ))
    return "\n".join(lines)


def snippets(source: Sequence[Mapping[str, Any]]) -> str:
    by_k = {int(row["k"]): row for row in source}
    require(set(by_k) == set(K_VALUES), "snippet source lacks the fixed tested grid")
    lines = [
        "% Generated V2.1 descriptive manuscript snippets from authenticated public r2 summary.",
        f"\\newcommand{{\\VTwoOneSeedCount}}{{{SEED_COUNT}}}",
        f"\\newcommand{{\\VTwoOneSourceFingerprint}}{{\\texttt{{{EXPECTED['source_code_fingerprint']}}}}}",
        f"\\newcommand{{\\VTwoOneConfigFingerprint}}{{\\texttt{{{EXPECTED['config_sha256']}}}}}",
        f"\\newcommand{{\\VTwoOneSolverFingerprint}}{{\\texttt{{{EXPECTED['solver_fingerprint']}}}}}",
        f"\\newcommand{{\\VTwoOnePaperRoot}}{{\\texttt{{{_tex_escape('results/' + DEFAULT_OUTPUT.name)}}}}}",
        "\\newcommand{\\VTwoOneDevelopmentCaveat}{These are 30-seed development-only descriptive means, not a confirmation, qualification, or threshold-selection result.}",
        "\\newcommand{\\VTwoOneReconstructionCaption}{Day-365 active-position and completed-operation P10 for the specified public checkpoint minimum-norm heuristic across categorical tested $k$ values and both traffic modes. Values are 30-seed development-only descriptive means; no threshold selection or confirmation is reported.}",
        "\\newcommand{\\VTwoOneHorizonTailCaption}{Filtered active-position P10 across the four fixed horizons and day-365 unreleased-tail fractions for both traffic modes. Marks are categorical 30-seed development-only descriptive means; no threshold selection or confirmation is reported.}",
    ]
    traffic_columns = (
        ("Filtered", "filtered_active_position_p10_day365", "filtered_completed_operation_p10_day365"),
        ("AllAddress", "all_addresses_active_position_p10_day365", "all_addresses_completed_operation_p10_day365"),
    )
    word = {1: "One", 2: "Two", 7: "Seven"}
    for k in (1, 2, 7):
        for traffic, position_column, operation_column in traffic_columns:
            lines.append(f"\\newcommand{{\\VTwoOne{traffic}K{word[k]}PositionPten}}{{{tex_pct(_source_value(by_k[k], position_column), 3)}}}")
            lines.append(f"\\newcommand{{\\VTwoOne{traffic}K{word[k]}OperationPten}}{{{tex_pct(_source_value(by_k[k], operation_column), 3)}}}")
    return "\n".join(lines) + "\n"


def paper_results(inputs: ValidatedInputs, source: Sequence[Mapping[str, Any]]) -> str:
    table_lines = [
        "| k | filtered active-position P10 | filtered completed-operation P10 | all-address active-position P10 | all-address completed-operation P10 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in source:
        table_lines.append(
            f"| {row['k']} | {markdown_pct(_source_value(row, 'filtered_active_position_p10_day365'))} | "
            f"{markdown_pct(_source_value(row, 'filtered_completed_operation_p10_day365'))} | "
            f"{markdown_pct(_source_value(row, 'all_addresses_active_position_p10_day365'))} | "
            f"{markdown_pct(_source_value(row, 'all_addresses_completed_operation_p10_day365'))} |"
        )
    by_k = {int(row["k"]): row for row in source}
    return f"""# V2.1 descriptive paper results

## Scope and caveat

This derivative bundle was generated from the authenticated external-safe public development summary in `{inputs.root.name}`. It contains 30 complete synthetic seed traces (`41001`--`41030`) as independent descriptive units. It is **not a confirmation, qualification, or threshold-selection result**. It does not support a deployed-vault conclusion, an optimal-attacker claim, or a general privacy guarantee.

The specified attacker is the deterministic public-prefix equal-weight minimum-norm checkpoint heuristic. It uses public action metadata and cumulative checkpoint shares, ignores public rate and asset fields, and has no amount priors, pseudonym profiles, NNLS fit, or rate-only arm. Pinned Yearn quantities remain generator calibration only and are not attacker inputs.

## Day-365 descriptive means

P10 is the seed-level fraction within 10% relative error. Active-position P10 is evaluated on evaluator-active positions after sealed estimation; completed-operation P10 refers to completed-window hidden share flow. Filtered traffic excludes known infrastructure; all-address traffic is a descriptive sensitivity. These values are means only, without interval or threshold analysis.

{chr(10).join(table_lines)}

## Reported categories

At `k=1`, filtered and all-address active-position and completed-operation P10 are each {markdown_pct(_source_value(by_k[1], 'filtered_active_position_p10_day365'))}. At `k=2`, filtered active-position/completed-operation P10 are {markdown_pct(_source_value(by_k[2], 'filtered_active_position_p10_day365'))}/{markdown_pct(_source_value(by_k[2], 'filtered_completed_operation_p10_day365'))}; all-address values are {markdown_pct(_source_value(by_k[2], 'all_addresses_active_position_p10_day365'))}/{markdown_pct(_source_value(by_k[2], 'all_addresses_completed_operation_p10_day365'))}. At `k=7`, filtered values are {markdown_pct(_source_value(by_k[7], 'filtered_active_position_p10_day365'))}/{markdown_pct(_source_value(by_k[7], 'filtered_completed_operation_p10_day365'))}; all-address values are {markdown_pct(_source_value(by_k[7], 'all_addresses_active_position_p10_day365'))}/{markdown_pct(_source_value(by_k[7], 'all_addresses_completed_operation_p10_day365'))}. These named categories are reported examples, not a chosen setting.

## Provenance and data boundary

The source/config/solver fingerprints are `{EXPECTED['source_code_fingerprint']}`, `{EXPECTED['config_sha256']}`, and `{EXPECTED['solver_fingerprint']}`. The input checksum inventory and every public provenance/summary file used by this generator were authenticated before output creation. This bundle contains only aggregate source rows and derivative presentation files; no row-level evaluator joins, action-level records, or participant identifiers are included.
"""


def create_manifest(output: Path, inputs: ValidatedInputs, figure_info: Sequence[tuple[str, int, int]]) -> None:
    hashes = {
        path.name: sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name not in {"manifest.json", "SHA256SUMS"}
    }
    payload = {
        "artifact_schema": ARTIFACT_SCHEMA,
        "generator_sha256": sha256(HERE),
        "evidence_status": "development_only_descriptive",
        "claim_boundary": "30-seed development-only descriptive material; no threshold selection or confirmation.",
        "input": {
            "root": f"results/{INPUT_ROOT_NAME}",
            "root_checksum_entries": EXPECTED_ROOT_CHECKSUM_ENTRIES,
            "root_checksum_inventory_sha256": inputs.inventory_sha256,
            "public_sources": dict(inputs.public_source_sha256),
            "schema_version": SCHEMA_VERSION,
            "phase": "development",
        },
        "provenance": dict(EXPECTED),
        "domain": {
            "seeds": [DEVELOPMENT_SEEDS[0], DEVELOPMENT_SEEDS[-1]],
            "seed_count": SEED_COUNT,
            "traffic_modes": list(TRAFFIC_MODES),
            "release": RELEASE,
            "horizons": list(HORIZONS),
            "k_values": list(K_VALUES),
        },
        "sources": [
            {"path": "v21_descriptive_results_source.csv", "rows": len(K_VALUES), "purpose": "table and reconstruction figure"},
            {"path": "v21_horizon_tail_source.csv", "rows": len(K_VALUES) * (len(HORIZONS) + len(TRAFFIC_MODES)), "purpose": "horizon and tail figure"},
        ],
        "figures": [
            {"stem": stem, "width_px": width, "height_px": height, "png_rgb_opaque": True}
            for stem, width, height in figure_info
        ],
        "generated_file_sha256": hashes,
        "timestamp": "omitted for deterministic reruns",
    }
    (output / "manifest.json").write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_bundle_checksums(output: Path) -> None:
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text("\n".join(f"{sha256(path)}  {path.name}" for path in files) + "\n", encoding="utf-8")


def verify_bundle_checksums(output: str | Path) -> dict[str, str]:
    root = _absolute(output)
    _assert_directory_non_symlink(root, label="V2.1 paper bundle")
    inventory = root / "SHA256SUMS"
    _assert_regular_non_symlink(inventory, label="V2.1 paper bundle checksum inventory")
    entries: dict[str, str] = {}
    for line in inventory.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as error:
            raise ValueError("invalid V2.1 paper checksum entry") from error
        candidate = Path(relative)
        require(len(digest) == 64 and all(char in "0123456789abcdef" for char in digest) and not candidate.is_absolute() and ".." not in candidate.parts and relative not in entries, "unsafe V2.1 paper checksum entry")
        entries[relative] = digest
    actual = {path.name for path in root.iterdir() if path.is_file() and path.name != "SHA256SUMS"}
    require(set(entries) == actual, "V2.1 paper checksum inventory is incomplete")
    for relative, digest in entries.items():
        _assert_regular_non_symlink(root / relative, label="V2.1 paper artifact")
        require(sha256(root / relative) == digest, f"V2.1 paper checksum mismatch: {relative}")
    return entries


def _assert_safe_output(target: Path) -> Path:
    candidate = _absolute(target)
    _assert_no_symlink_components(candidate)
    prohibited = (
        RESULTS_ROOT / INPUT_ROOT_NAME,
        RESULTS_ROOT / ATTEMPT_1_ROOT_NAME,
        *(path for path in RESULTS_ROOT.glob("stage_b_*") if path.is_dir()),
    )
    for protected in prohibited:
        try:
            candidate.relative_to(_absolute(protected))
        except ValueError:
            continue
        raise ValueError("refusing to write within a protected evidence or development root")
    require(candidate.parent.is_dir(), f"paper output parent does not exist: {candidate.parent}")
    require(not candidate.exists(), f"refusing to overwrite existing V2.1 paper output: {candidate}")
    return candidate


def _assert_no_symlink_components(path: Path) -> None:
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode):
            if current in {Path("/var"), Path("/tmp")}:
                continue
            raise ValueError(f"paper output path contains a symlink: {current}")
        if current != absolute:
            require(stat.S_ISDIR(metadata.st_mode), f"paper output parent is not a directory: {current}")


def _prepare_output(output: Path) -> tuple[Path, Path, Path]:
    target = _assert_safe_output(output)
    lock = target.parent / f".{target.name}.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError(f"another V2.1 paper generation holds the exclusive lock: {lock}") from error
    else:
        os.close(descriptor)
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp.", dir=target.parent))
    except Exception:
        lock.unlink(missing_ok=True)
        raise
    return target, stage, lock


def _publish_output(stage: Path, target: Path) -> None:
    # The exclusive lock prevents two cooperating generators from racing.  A
    # final existence check ensures this generator never intentionally replaces
    # an already published sibling.
    require(not target.exists(), "refusing to replace an existing V2.1 paper output")
    os.replace(stage, target)


def generate_from_validated(inputs: ValidatedInputs, output: str | Path = DEFAULT_OUTPUT) -> Path:
    """Generate the compact derivative bundle atomically into a fresh sibling."""

    target, stage, lock = _prepare_output(Path(output))
    try:
        results = build_results_source(inputs)
        horizon_tail = build_horizon_tail_source(inputs)
        write_csv(stage / "v21_descriptive_results_source.csv", RESULTS_SOURCE_COLUMNS, results)
        write_csv(stage / "v21_horizon_tail_source.csv", HORIZON_TAIL_SOURCE_COLUMNS, horizon_tail)
        (stage / "v21_descriptive_results_table.tex").write_text(descriptive_table(results), encoding="utf-8")
        (stage / "v21_snippets.tex").write_text(snippets(results), encoding="utf-8")
        (stage / "PAPER_RESULTS.md").write_text(paper_results(inputs, results), encoding="utf-8")
        figures = [reconstruction_figure(results, stage), horizon_tail_figure(horizon_tail, stage)]
        create_manifest(stage, inputs, figures)
        write_bundle_checksums(stage)
        verify_bundle_checksums(stage)
        _publish_output(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        lock.unlink(missing_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate V2.1 development-only descriptive paper artifacts")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="fresh V2.1 paper sibling output")
    args = parser.parse_args(argv)
    try:
        inputs = validate_inputs(DEFAULT_ROOT)
        generate_from_validated(inputs, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
