# Paper reproduction

From this repository root, with Python 3.10 or later and Make:

```sh
make paper-table
```

This standard-library-only command verifies `SHA256SUMS` for the shipped public bundle before printing all 15 percentages in the paper's reconstruction table. It selects `filtered_completed_operation_p10_day365`, the filtered-cohort day-365 mean across 30 seeds, multiplies by 100, and rounds to two decimals. It does not rerun simulations or average the already averaged CSV values again. `make verify-artifacts` checks the bundle without printing the table.

## Optional new synthetic smoke run

```sh
make setup
make smoke
```

Setup creates `.venv` and installs both `requirements-v2.lock` and the package. The smoke target runs only V2.1 seed 41001, limits numerical libraries to one thread, and creates a fresh `results/local-v21-smoke-*` directory. It never uses the protected canonical result path. `make test` runs the focused public V2.1 tests after setup. Set `PYTHON=/path/to/python3` when a specific interpreter is needed.

The smoke run is a new development-only synthetic experiment, not regeneration of the published 30-seed evidence. Its `private/` evaluator join must not be published. The public repository omits the canonical evidence root required by `paper/generate_v21_artifacts.py`; the helper verifies and displays the public bundle without claiming a complete historical audit. See `RUN_LOCALLY.md` and `V21_PROTOCOL.md` for the full scientific and availability boundaries.
