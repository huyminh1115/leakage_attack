# Public Standalone Leakage Runbook

This runbook is for the public, runnable package. It covers local validation and safe new simulations; it does not reproduce or audit the access-controlled canonical V2.1 r2 evidence root.

## Environment

Use Python 3.10 or newer, create a virtual environment, install the package and frozen numerical dependencies, and limit numerical libraries to one thread. Exact commands are in [RUN_LOCALLY.md](RUN_LOCALLY.md).

## Validation

Run the focused V2.1 tests and the V50 tests from this package. The paper-artifact test is deliberately not shipped because it authenticates the excluded complete r2 inventory, including protected private entries.

## Safe local output

Always write V2.1 and V50 smoke runs to a new `results/local-*` directory. Do not point a smoke run at `results/public_checkpoint_min_norm_v21_development_30_r2` (which is absent) or overwrite any prior output. V2.1 local output includes private synthetic truth joins for evaluation; do not distribute them.

## Public paper bundle

Verify the shipped descriptive bundle with its `SHA256SUMS` file. `paper/generate_v21_artifacts.py` remains available for code transparency, but cannot regenerate the bundle from this package: the required complete canonical r2 evidence root is intentionally excluded.

For precise scientific assumptions and limitations, read [V21_PROTOCOL.md](V21_PROTOCOL.md) and [V50_PROTOCOL.md](V50_PROTOCOL.md).
