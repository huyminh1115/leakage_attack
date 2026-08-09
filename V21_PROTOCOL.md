> **Standalone-package notice:** This public package includes the runnable synthetic code, frozen calibration, and public paper-artifact bundle only. It does **not** include the complete canonical V2.1 r2 evidence root or any private truth joins. References below to that access-controlled canonical root describe the original protocol and are not executable from this package.

# V2.1 public-checkpoint minimum-norm development protocol

## Status and scope

This document specifies the current **development-only** experiment namespace:
`public_checkpoint_min_norm_v21_r2`. Its authenticated result root and paper
sibling remain unchanged. The obsolete V1/V2 study evidence and tooling were
removed after the V2.1 paper transition; only the byte-pinned private-generator
bridge required by r2 provenance is retained. V2.1 has no confirmatory seed
range, launch lock, confidence-bound qualification, or tested-k choice.
User-authorized paper use is limited to a separate derivative of the
authenticated public development summary; it remains 30-seed development-only
descriptive material, not confirmation, qualification, or threshold selection.

V2.1 evaluates one deliberately simple attacker implementation:

> a deterministic numerical, public-prefix, equal-weight minimum-norm
> checkpoint heuristic.

It is not an exact/certified solver, an optimal-attacker theorem, a privacy
theorem, or a deployed-vault study. Any future decision to make a new
scientific claim beyond this descriptive paper use requires a separate
protocol and fresh approval.

## Fixed development domain

- seeds: `41001` through `41030` only;
- traffic modes: `known_infrastructure_excluded` and `all_addresses`;
- ordinary reset-based strict-k grid:
  \[
  \{1,2,3,4,5,6,7,8,9,10,15,20,30,40,50\};
  \]
- horizons: days 30, 90, 180, and 365, interpreted as records with
  `day < horizon`;
- one release: `checkpoint_totals`.

For each `(seed, traffic mode)`, v2.1 reuses one fresh zero-start synthetic
latent trace across every `k`.  It independently recomputes the ordinary
reset-based strict-k partition for each `k`, so partitions for different
values are not assumed nested.  A release follows the action introducing the
`k`-th distinct eligible pseudonym; there is no deadline, forced release, or
terminal flush.  Final incomplete windows are right-censored.

The private generator uses the retained byte-pinned bridge
`v2_calibration.py`, `v2_config.py`, `v2_disclosure.py`, and
`v2_simulator.py`; `v2_paths.py` remains only because the calibration module
imports its fail-closed path helper. `results/v2_empirical_inputs.json` is the
frozen calibration payload. These V2-named files are current V2.1 implementation
provenance, not retained historical-study evidence. Pinned Yearn-derived
quantities remain generator calibration only; no Yearn transaction is replayed
as a vault action.

## Public estimator seam

The sole attacker API is:

```python
estimate(public_transcript, horizon)
```

It accepts only public action ID, action order/day/tick, stable eligible
pseudonym, deposit/withdraw direction, and cumulative
`checkpoint_shares`.  It permits the emitted public `rate` and
`checkpoint_assets` fields for transcript compatibility, but does not read
or use either field.  It rejects truth fields, unknown fields, malformed
ordering, non-`checkpoint_totals` releases, malformed checkpoint sequences,
and infeasible/numerically unresolved inputs.

The estimator imports no calibration module and has no amount-scale priors,
pseudonym amount parameters, profile fitting, NNLS, rate-only arm, feasible
intervals, or certificates.  It permits only the already pinned NumPy/SciPy
runtime, including its HiGHS and SLSQP implementations; additional or new
solver packages, native installations, alternate backends, and fallbacks are
prohibited.

### Causal prefix and tail policy

At a horizon, only public records with `day < horizon` are visible.  Let the
last visible completed checkpoint end at action index `e`.  The numerical fit
uses all and only public actions through `e`; it never reads later records.
Every visible action after that checkpoint receives an explicit estimate of
zero with `tail_abstention=true` and does not change an estimated position.
When no completed checkpoint is visible, every visible action is a zero-tail
abstention and every estimated position remains zero.

Thus later released checkpoints may revise estimates for earlier completed
actions, while later records cannot alter an earlier horizon's output.

### Numerical heuristic

For action magnitude variables \(x_i\in\mathbb{R}_{\ge0}\), sign
\(s_i=+1\) for deposits and \(-1\) for withdrawals, and each visible
completed checkpoint \(c\), v2.1 imposes

\[
\sum_{i\le e_c}s_i x_i=S_c.
\]

For every eligible pseudonym and modeled public action prefix, it also imposes
nonnegative reconstructed balance.  It uses no aggregate slack, clipping,
integer repair, or alternate numerical fallback.

Let

\[
M=\max\left(1,\max_c |S_c|\right).
\]

Among the feasible continuous allocations, v2.1 chooses the unique
minimum-norm tie break

\[
\min_x\ \frac12\sum_i(x_i/M)^2.
\]

The implementation first obtains a feasible point with pinned
`scipy.optimize.linprog(method="highs-ds", options={"presolve": False})`, then
invokes deterministic `scipy.optimize.minimize(method="SLSQP")` with analytic
objective gradient and linear equality/inequality Jacobians.  The frozen SLSQP
settings are `ftol=1e-9`, `maxiter=1000`; the fixed HiGHS setting disables
presolve.  It validates finite outputs, maximum normalized
checkpoint residual at most `1e-7`, and minimum normalized balance at least
`-1e-7`.  A failed check is a failed cell, not a repaired score.

This is a numerical implementation convention, not a proof that the
continuous allocation is exact or a globally optimal attacker under another
loss function.

## Private evaluation boundary

The attacker result is sealed before hidden synthetic truth is joined.  The
private evaluator joins by stable action ID and reports:

- active-position P10 at each horizon, over positions with private true
  balance greater than zero;
- completed-operation P10;
- tail-operation P10; and
- all-visible-operation P10.

P10 uses the inclusive condition
\(|\widehat z-z|\le 0.10z\).  If a seed/horizon has no truth-active
positions, its active-position P10 is zero and the zero denominator is
retained rather than dropped.  Completed, tail, and all operation populations
remain separate descriptive measures.

## Output, provenance, and safe execution

The canonical corrected r2 full development root is reserved for an explicitly
invoked complete 30-seed run:

```text
results/public_checkpoint_min_norm_v21_development_30_r2/
```

The prior `results/public_checkpoint_min_norm_v21_development_30/` root is a
checksum-protected, superseded diagnostic attempt 1. It is non-evidence and is
never edited, reused, summarized, or treated as an r2 result. The r2 runner
pins `scipy.optimize.linprog(method="highs-ds", options={"presolve": False})`
in both its config and source fingerprints after the attempt-1 false-
infeasibility diagnosis. The runner creates a new root exclusively, refuses
every existing output, and continues to deny legacy V1/V2 result names even
though those roots were deleted. It uses no-follow/exclusive creation for
directories and files. The canonical root refuses a subset; use a fresh staging
path for a one-seed smoke run.

The root has separated trees:

- `public/`: seed-level metrics, solver diagnostics, public action estimates,
  and, after a complete 30-seed run, an external-safe descriptive summary;
- `private/`: per-seed truth joins used only after sealing public estimates.

No external summary contains operation-level truth rows. The root records raw
and semantic config hashes, calibration hash, pinned dependency-lock hash,
solver fingerprint, a fingerprint of only `v21_*.py`, and separate hashes for
the explicitly reused unchanged generator-bridge modules. The recorded bridge
hash remains the current provenance authority for those retained bytes.

A complete development summary reports descriptive seed-level P10 values,
solver failures/runtime, and tail rates by traffic mode, `k`, and horizon. It
never performs a confidence bound, a threshold decision, or a tested-k
choice. The user-authorized paper derivative is the exclusive sibling
`results/public_checkpoint_min_norm_v21_development_30_r2_paper/`. Its
generator streams the full r2 root only to authenticate the closed checksum
inventory and derives values only from aggregate public summary/provenance
sources. It never parses or exports the `private/` truth joins or row-level
public metrics. It emits only a 15-row descriptive table, two descriptive
figures, source CSVs, snippets, a digest, manifest, and
checksums. It must preserve the same development-only, non-confirmation,
non-qualification claim boundary.

## Command

With the existing pinned environment active:

```bash
cd experiments/leakage_attack
. .venv-v2/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1

# Safe one-seed staging smoke; it cannot write the canonical 30-seed root.
PYTHONPATH=src python -m leakage_attack.v21_development_cli \
  --seed 41001 --output results/local-v21-smoke-$(date +%Y%m%d-%H%M%S)
```

Do not invoke the no-argument canonical 30-seed command until a separate
review authorizes that development run. There is intentionally no
confirmatory command in this lineage. After the complete r2 root exists, the
user-authorized descriptive derivative may be generated once into its absent
sibling and authenticated as follows:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python paper/generate_v21_artifacts.py
(cd results/public_checkpoint_min_norm_v21_development_30_r2_paper && shasum -a 256 -c SHA256SUMS)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python -m unittest tests/test_v21_paper_artifacts.py -v
```
