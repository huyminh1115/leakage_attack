"""Small fail-closed path helpers for the separate v2.1 development lineage."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from .v21_config import CANONICAL_DEVELOPMENT_OUTPUT_ROOT

EXPERIMENT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = EXPERIMENT_ROOT / "results"
# Attempt 1 is an immutable diagnostic root. The corrected r2 contract is
# the only canonical root that a new full development run may create.
DIAGNOSTIC_ATTEMPT_1_ROOT = RESULTS_ROOT / "public_checkpoint_min_norm_v21_development_30"
CANONICAL_DEVELOPMENT_ROOT = EXPERIMENT_ROOT / CANONICAL_DEVELOPMENT_OUTPUT_ROOT


def immutable_v1_v2_roots() -> tuple[Path, ...]:
    """Return every existing historical Stage B root that v2.1 must not touch."""

    names = {
        "stage_b_k_only_confirmatory_100",
        "stage_b_k_only_confirmatory_100_precleanup_integrity",
        *(
            path.name for path in RESULTS_ROOT.glob("stage_b_repeated_aggregate_nnls_v2_*")
            if path.is_dir()
        ),
    }
    return tuple(sorted((RESULTS_ROOT / name for name in names), key=lambda path: path.name))


def _absolute(path: str | Path) -> Path:
    raw = Path(path).expanduser()
    return raw if raw.is_absolute() else (Path.cwd() / raw)


def _assert_existing_components_are_not_symlinks(path: Path) -> None:
    """Reject any existing component that could redirect a later writer."""

    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode):
            # macOS exposes its normal temporary hierarchy through /var (and
            # commonly /tmp).  Permit only these OS-owned compatibility links;
            # every project- or caller-provided link remains a hard failure.
            if current in {Path("/var"), Path("/tmp")}:
                continue
            raise ValueError(f"v2.1 output path contains a symlink: {current}")
        if current != absolute and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"v2.1 output parent is not a directory: {current}")


def _is_historical_name(path: Path) -> bool:
    try:
        relative = _absolute(path).resolve(strict=False).relative_to(RESULTS_ROOT.resolve())
    except ValueError:
        return False
    return any(
        component == "stage_b_k_only_confirmatory_100"
        or component == "stage_b_k_only_confirmatory_100_precleanup_integrity"
        or component.startswith("stage_b_repeated_aggregate_nnls_v2_")
        for component in relative.parts
    )


def _is_diagnostic_attempt_1(path: Path) -> bool:
    return _absolute(path).resolve(strict=False) == DIAGNOSTIC_ATTEMPT_1_ROOT.resolve()


def reject_protected_or_existing_output(path: str | Path) -> Path:
    """Return a safe absent destination or reject protected/existing targets."""

    candidate = _absolute(path)
    _assert_existing_components_are_not_symlinks(candidate)
    if _is_historical_name(candidate):
        raise ValueError("refusing to write within a protected v1/v2 result root")
    if _is_diagnostic_attempt_1(candidate):
        raise ValueError("refusing to write within the immutable v2.1 diagnostic attempt 1 root")
    try:
        metadata = os.lstat(candidate)
    except FileNotFoundError:
        return candidate
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("v2.1 output root must not be a symlink")
    raise ValueError(f"refusing to overwrite existing v2.1 output: {candidate}")


def prepare_new_output_root(path: str | Path) -> Path:
    """Create exactly one new root through an exclusive operation."""

    candidate = reject_protected_or_existing_output(path)
    _assert_existing_components_are_not_symlinks(candidate.parent)
    if not candidate.parent.is_dir():
        raise ValueError(f"v2.1 output parent does not exist: {candidate.parent}")
    try:
        os.mkdir(candidate, mode=0o700)
    except FileExistsError as error:
        raise ValueError(f"refusing to overwrite existing v2.1 output: {candidate}") from error
    metadata = os.lstat(candidate)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("v2.1 exclusive output creation did not produce a directory")
    return candidate


def require_output_root(path: str | Path) -> Path:
    """Authenticate an already created v2.1 root before descriptor-safe writes."""

    candidate = _absolute(path)
    _assert_existing_components_are_not_symlinks(candidate)
    if _is_historical_name(candidate):
        raise ValueError("refusing to write within a protected v1/v2 result root")
    if _is_diagnostic_attempt_1(candidate):
        raise ValueError("refusing to write within the immutable v2.1 diagnostic attempt 1 root")
    try:
        metadata = os.lstat(candidate)
    except FileNotFoundError as error:
        raise ValueError(f"v2.1 output root is missing: {candidate}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("v2.1 output root must be a non-symlink directory")
    return candidate


def create_child_directory(parent: str | Path, name: str) -> Path:
    """Exclusively create one simple child directory beneath a safe root."""

    if not name or name in {".", ".."} or "/" in name:
        raise ValueError("v2.1 child directory name is invalid")
    root = require_output_root(parent)
    child = root / name
    _assert_existing_components_are_not_symlinks(child)
    try:
        os.mkdir(child, mode=0o700)
    except FileExistsError as error:
        raise ValueError(f"refusing to overwrite existing v2.1 child: {child}") from error
    metadata = os.lstat(child)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("v2.1 child creation did not produce a directory")
    return child


def write_new_bytes(parent: str | Path, name: str, data: bytes) -> Path:
    """Create one regular file with O_EXCL/O_NOFOLLOW and complete writes."""

    if not name or name in {".", ".."} or "/" in name:
        raise ValueError("v2.1 output file name is invalid")
    if not isinstance(data, bytes):
        raise TypeError("v2.1 output data must be bytes")
    directory = require_output_root(parent)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise ValueError("v2.1 output publication requires O_NOFOLLOW and O_DIRECTORY")
    directory_fd: int | None = None
    descriptor: int | None = None
    created = False
    try:
        directory_fd = os.open(directory, os.O_RDONLY | directory_flag | no_follow)
        directory_stat = os.fstat(directory_fd)
        named_stat = os.lstat(directory)
        if not stat.S_ISDIR(directory_stat.st_mode) or (directory_stat.st_dev, directory_stat.st_ino) != (named_stat.st_dev, named_stat.st_ino):
            raise ValueError("v2.1 output directory changed before publication")
        descriptor = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow, 0o600, dir_fd=directory_fd,
        )
        created = True
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("v2.1 output file is not a singly linked regular file")
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short v2.1 descriptor write")
            view = view[written:]
        os.fsync(descriptor)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        # Best-effort removal is restricted to the pinned directory descriptor.
        if created and directory_fd is not None:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_fd is not None:
            os.close(directory_fd)
    return directory / name


def write_new_text(parent: str | Path, name: str, text: str) -> Path:
    """Text counterpart retained as a small public writer seam."""

    return write_new_bytes(parent, name, text.encode("utf-8"))


__all__ = [
    "CANONICAL_DEVELOPMENT_ROOT", "DIAGNOSTIC_ATTEMPT_1_ROOT", "EXPERIMENT_ROOT", "RESULTS_ROOT",
    "create_child_directory",
    "immutable_v1_v2_roots", "prepare_new_output_root", "reject_protected_or_existing_output",
    "require_output_root", "write_new_bytes", "write_new_text",
]
