# World Cup 2026 Model Iteration Workflow

This reference captures the reusable workflow established for the `football-predictor` skill when building the World Cup 2026 national-team prediction model.

## User-Approved Scope

- Target: World Cup 2026 national-team matches.
- Markets: 1X2, over/under 2.5, and betting value.
- Training data: only `FIFA World Cup` and `FIFA World Cup qualification`.
- Historical window: from `2014-06-12` onward through data available before kickoff.
- Excluded unless explicitly changed: continental cups, continental qualifiers, Nations League, friendlies, Olympic/U23, CONIFA, Viva World Cup.

## Default Modeling Route

1. Import and filter historical match data.
2. Build rolling Elo-style strength estimates.
3. Generate Poisson + Dixon-Coles score distribution.
4. Post-calibrate O/U probabilities with shrinkage.
5. Compare 1X2 probabilities against normalized market odds when odds are present.
6. Grade output through betting signal discipline.

## Current Calibrated Parameters

Use these as the default baseline until a later calibration supersedes them:

| Parameter | Value |
|-----------|-------|
| `league_avg` | `1.35` |
| `home_advantage` | `1.12` |
| `dixon_coles_rho` | `-0.04` |
| `min_training_matches` | `300` |
| `ou_base_rate` | `0.45` |
| `ou_shrinkage` | `0.45` |

## Current Performance Snapshot

After O/U shrinkage:

| Metric | Value |
|--------|-------|
| Backtested matches | `2514` |
| 1X2 accuracy | `58.6%` |
| O/U 2.5 accuracy | `56.2%` |
| 1X2 log loss | `0.8956` |
| O/U 2.5 log loss | `0.6805` |
| 1X2 ECE | `0.047` |
| O/U 2.5 ECE | `0.057` |

## Signal Discipline

- `1X2 value` is the primary betting signal.
- `O/U 2.5 lean` is secondary only and should not trigger standalone bets without historical odds/ROI validation.
- Grade A 1X2 can be actionable when edge and model probability thresholds pass.
- O/U lean can support interpretation but should not justify larger stake.

## Autonomous Execution Preference

For this class of iterative model-building work, continue autonomously through obvious next engineering steps:

- Add or modify scripts.
- Run import/backtest/calibration/probability-calibration commands.
- Update generated reports.
- Sync `SKILL.md`, `config/project.yaml`, and relevant `references/` docs.

Ask the user only for decisions that change goals, scope, data universe, risk tolerance, or tradeoff priorities.

## Next Recommended Step

Before claiming betting profitability, add a manual odds CSV schema and ROI backtest framework. Historical odds are required to evaluate whether model edges become positive expected return after market overround and realistic selection rules.
