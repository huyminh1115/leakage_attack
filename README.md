# Leakage Attack Simulations

A public, standalone Python repository for two **synthetic** studies of information leakage from checkpoint-style public data. It is research code, not a deployed-vault study, a cryptographic privacy guarantee, or a recommendation for a production threshold.

- **V2.1** is a development-only, public-checkpoint minimum-norm simulation. Its deterministic synthetic generator uses frozen aggregate calibration inputs. It does not replay real vault transactions.
- **V50** is a separate exploratory current-share simulation with its own generator, estimator, tests, and output namespace.

Read [V21_PROTOCOL.md](V21_PROTOCOL.md) and [V50_PROTOCOL.md](V50_PROTOCOL.md) before interpreting outcomes. [RUN_LOCALLY.md](RUN_LOCALLY.md) provides a reproducible local setup, focused validation commands, and safe smoke runs.

## Repository contents

- `src/leakage_attack/` — runnable V2.1, retained V2.1 generator-bridge, and V50 Python code.
- `tests/` — focused V2.1 and V50 unit tests.
- `config/` and `results/v2_empirical_inputs.json` — the V2.1 development configuration and frozen calibration input.
- `results/public_checkpoint_min_norm_v21_development_30_r2_paper/` — public descriptive figures, tables, source CSVs, an inventory, and checksums.
- `paper/generate_v21_artifacts.py` — the original paper-bundle generator, included for transparency.
- `RUNBOOK.md`, `V21_PROTOCOL.md`, and `V50_PROTOCOL.md` — execution and scientific-boundary documentation.

## Public/private boundary

This repository intentionally excludes the complete canonical V2.1 r2 evidence root, all superseded full-result roots, and every `private/` subtree (including synthetic `truth_join` files). The included paper bundle can be checksum-verified, but it cannot be regenerated or fully audited from this public repository: its generator validates an access-controlled canonical evidence inventory that is deliberately absent here.

New local V2.1 smoke runs create `results/local-v21-*` and include a synthetic evaluator join below `private/`; do **not** publish that subtree. New V50 runs create `results/local-v50-*`; those outputs are also local experimental material, not published evidence. `.gitignore` protects all locally generated result trees while retaining only the reviewed calibration input and public paper bundle.

## Installation and validation

Python **3.10 or later** and internet access for the first dependency installation are required. The package metadata declares the installable project; `requirements-v2.lock` pins the numerical runtime used for repeated runs. From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-v2.lock
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests -p 'test_public_checkpoint_v21*.py' -v
PYTHONPATH=src python -m unittest tests/test_v50.py -v
```

For the complete commands, safe fresh-output workflow, and artifact checksum verification, see [RUN_LOCALLY.md](RUN_LOCALLY.md).

## Calibration and limitations

`results/v2_empirical_inputs.json` is a frozen aggregate calibration payload containing address-labelled activity records used by the synthetic generator. It is not a replay of vault transactions and should not be treated as a privacy claim about any deployment. The payload is derived from Yearn-related data; users who redistribute or adapt it must independently confirm their rights and comply with applicable source terms, attribution requirements, and data policies.

Results are development-only and descriptive. They do not establish an optimal attacker, a certified solver, a safe parameter, real-world leakage, or a security/privacy guarantee. See the protocol documents for the fixed assumptions, estimator boundaries, and limitations.

## License

This repository is available under the [MIT License](LICENSE).
