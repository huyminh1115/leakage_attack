# Run Locally

These commands run the public synthetic simulations from a fresh checkout. They do not reproduce the access-controlled canonical V2.1 r2 evidence root.

## Requirements

- Python **3.10 or later**.
- Internet access for the initial package download.
- A POSIX-like shell for the example environment variables and timestamped output paths.

## Create an isolated environment

`pyproject.toml` defines the installable package and supported Python version. `requirements-v2.lock` pins the numerical packages used by the experiments; install both rather than treating the lock file as a standalone package definition.

```bash
python3 --version
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-v2.lock
python -m pip install -e .
```

For more consistent local numerical behavior, limit numerical libraries to one thread:

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
```

## Validate the public code

```bash
PYTHONPATH=src python -m compileall -q src tests paper
PYTHONPATH=src python -m unittest discover -s tests -p 'test_public_checkpoint_v21*.py' -v
PYTHONPATH=src python -m unittest tests/test_v50.py -v
```

The V2.1 paper-artifact test is intentionally unavailable: it authenticates the excluded complete canonical r2 inventory, including protected private entries.

## Make safe, new local output

Always select a fresh directory under `results/`. Do not overwrite the shipped calibration input or public paper bundle.

### V2.1 public-checkpoint smoke run

```bash
RUN="results/local-v21-smoke-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src python -m leakage_attack.v21_development_cli \
  --seed 41001 --output "$RUN"
find "$RUN" -maxdepth 3 -type f | sort
```

This creates a one-seed synthetic staging run. Its `private/seed_41001/truth_join.csv.gz` file is an evaluator-only synthetic truth join; do **not** share or publish it.

### V50 exploratory smoke run

```bash
RUN="results/local-v50-smoke-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src python -m leakage_attack.v50_cli \
  --seed 50001 --k 1 --k 10 --k 50 --output "$RUN"
find "$RUN" -maxdepth 1 -type f | sort
```

This creates local `run_summary.csv`, `snapshot_trajectory.csv`, and `run_metadata.json` output. It is exploratory local output, not published evidence.

## Verify the shipped paper artifacts

```bash
(cd results/public_checkpoint_min_norm_v21_development_30_r2_paper && \
  shasum -a 256 -c SHA256SUMS)
```

The original bundle generator is included at `paper/generate_v21_artifacts.py` for review. It cannot regenerate the public bundle from this repository because it intentionally requires the absent, access-controlled complete canonical r2 evidence root. Do not substitute a local smoke run for that evidence root.

## Calibration and interpretation

The frozen `results/v2_empirical_inputs.json` calibration payload includes address-labelled aggregate records and is used only by the synthetic V2.1 generator. It is not a transaction replay or a claim about a deployed system. Before redistributing or changing it, independently verify any Yearn-source licensing, attribution, and data-policy obligations. The simulation results do not establish a production-safe parameter, a privacy/security guarantee, or real-world leakage.
