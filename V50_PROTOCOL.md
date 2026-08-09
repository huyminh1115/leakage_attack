> **Standalone-package notice:** This public package includes the runnable synthetic code, frozen calibration, and public paper-artifact bundle only. It does **not** include the complete canonical V2.1 r2 evidence root or any private truth joins. References below to that access-controlled canonical root describe the original protocol and are not executable from this package.

# V50 k-only current-share safety experiment

## Scope

V50 is an **independent experimental** synthetic study. It reports per-seed distributions and release trajectories of attacker leakage `L10` and safety `S10`; it selects no safe `k` and makes no deployed-system or cryptographic-safety claim. It does not revise or reuse the current V2.1 result.

## Fixed workload and disclosure

Each public seed `50001..50010` generates one trace of 10,000 operations reused across `k ∈ {1,2,3,5,6,8,10,20,30,50}`. The population is 100 fixed actors, zero-start shares, and uniform actor selection. Per-actor true profile magnitudes are discretized log-normal (median 100 microshares, GSD 2). Operation amount is `max(1, round(p_i ξ))`, where `ξ` is log-normal with mean 1 and GSD 1.25.

An actor with zero balance, or with equal public cumulative deposit and withdrawal counts, must deposit; otherwise direction is 50/50. Withdrawal executes `min(requested, current balance)`. These rules preserve true-balance and public-count feasibility.

A window releases immediately upon its `k`th distinct actor, then resets. Membership is exactly `S_t`; an actor enters a later window only following a new operation. The public release is `Y_t = sum_{i in S_t} B_i(t)` using post-window balances. The final incomplete window is censored, never flushed.

## Public attacker and evaluation boundary

The attacker sees only stable `S_t`, `Y_t`, and actor cumulative deposit/withdraw counts. The public transcript rejects any count that regresses from the immediately preceding release. It has one non-negative coefficient per actor:

`Bhat_i(t) = p_i (D_i(t) - W_i(t))`.

It uses causal non-negative ridge based on incremental Gram/response sufficient statistics. Before observing `Y_t`, every candidate predicts it and records squared aggregate loss. Candidates are `max(1, tr(G)/100) × {1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1, 10}`; rolling loss spans 50 releases and ties choose the larger lambda. Before 10 prior releases, the largest lambda is used and output is warm-up. Lambda selection precedes the update with `Y_t`; score reconstruction is then emitted. The estimator never receives profile, amount, or balance truth and never uses future releases.

The evaluator joins sealed predictions to private post-release balances. For truth-active (`B_i(t)>0`) actors only, `L10(t)` is the inclusive fraction with relative error at most 10%; `S10(t)=1-L10(t)`. All snapshots are emitted. The first ten warm-up snapshots are reported separately and excluded from primary run-level means.

## Execution

```bash
cd experiments/leakage_attack
PYTHONPATH=src python -m leakage_attack.v50_cli --seed 50001 --k 1 --k 10 --k 50 \
  --output results/local-v50-smoke
```

Outputs are a new directory containing `run_summary.csv`, `snapshot_trajectory.csv`, and `run_metadata.json`. A full campaign is explicit by omitting `--seed` and `--k`; it should only be run after a staging benchmark.
