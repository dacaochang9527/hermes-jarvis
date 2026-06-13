# World Cup 2026 Model Evolution Workflow

Use this workflow when extending the `football-predictor` skill for the user's World Cup 2026 prediction project.

## User-Decision First

Before collecting data or changing models, lock down the user's choices in durable project files:

1. Target event and match type.
2. Prediction markets: 1X2, over/under, value betting, etc.
3. Training competition scope.
4. Historical time window.
5. Data source and import policy.
6. Evaluation objective.

Write accepted decisions to:

- `config/project.yaml` for machine-readable configuration.
- `references/world-cup-2026-scope.md` for human-readable scope.
- `references/data-schema.md` when the choice affects source fields or filtering.
- `SKILL.md` file list / model roadmap when future agents need to see it immediately.

## Current Approved Scope

Current user-approved scope:

- Target: World Cup 2026 national-team matches.
- Markets: 1X2, over/under 2.5, betting value.
- Training competitions: `FIFA World Cup` and `FIFA World Cup qualification` only.
- Excluded: continental cups, continental qualifiers, Nations League, friendlies, Olympic/U23.
- Historical window: from `2014-06-12` onward, using only data available before predicted-match kickoff.

## Data Pipeline Pattern

1. Prefer a public downloadable source with stable columns.
2. Verify source fields before writing import code.
3. Filter strictly by approved scope; exclude similarly named competitions such as `CONIFA World Cup qualification` and `Viva World Cup`.
4. Skip future/unplayed rows with missing scores such as `NA`.
5. Preserve provenance fields like source URL and neutral venue.
6. Generate both JSON for scripts and CSV for inspection.
7. Validate row count, date range, tournament names, and score types after import.

## Evaluation Pattern

Use rolling backtests only:

1. Sort matches chronologically.
2. For each match, train only on prior matches.
3. Evaluate both accuracy and log loss.
4. Prefer log loss for model calibration because betting value depends on probability quality.
5. Do not evaluate ROI until historical odds are available.

## Calibration Pattern

For first-pass calibration:

1. Optimize a weighted objective such as `0.7 * log_loss_1x2 + 0.3 * log_loss_ou25`.
2. Grid search `league_avg`, home advantage, Dixon-Coles `rho`, and minimum training window.
3. Save full grid results to `reports/calibration_results.csv`.
4. Save selected parameters to `reports/calibration_best.json`.
5. Sync selected parameters into `config/project.yaml` and CLI defaults.

## Next Recommended Step

After parameter calibration, run probability calibration analysis:

- Bin predicted probabilities, e.g. 40-50%, 50-60%, 60-70%.
- Compare predicted probability with observed frequency.
- Check separately for 1X2 and over/under.
- Use this before trusting betting-value output.
