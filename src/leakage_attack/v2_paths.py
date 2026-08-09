"""Filesystem guards shared by all v2 evidence writers.

V2 development and confirmatory outputs must never mutate the immutable v1
archive.  The check intentionally resolves symlinks and normalizes missing
children through their existing parents before testing containment.
"""
from __future__ import annotations

from pathlib import Path


EXPERIMENT_ROOT = Path(__file__).resolve().parents[2]
IMMUTABLE_V1_ROOT = EXPERIMENT_ROOT / "results" / "stage_b_k_only_confirmatory_100"


def assert_not_within_immutable_v1_root(path: str | Path) -> Path:
    """Resolve *path* and reject the v1 root, its descendants, and symlinks.

    The returned resolved path is convenient for writers that need a canonical
    destination.  ``Path.resolve`` follows existing symlinks while also
    normalizing a not-yet-created final component, so both direct and indirect
    containment are refused before opening a file.
    """

    candidate = Path(path).expanduser().resolve()
    immutable = IMMUTABLE_V1_ROOT.resolve()
    try:
        candidate.relative_to(immutable)
    except ValueError:
        return candidate
    raise ValueError(f"refusing to write within immutable v1 evidence root: {immutable}")
