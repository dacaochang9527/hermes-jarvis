# Model Calibration Workflow

Use this workflow for iterative sports-prediction model work when the user has already approved the target scope.

## Operating Mode

- Ask the user only for option-type decisions that change goals, scope, data universe, or tradeoffs.
- Once a scope decision is made, autonomously implement the next engineering step: scripts, data import, backtests, calibration, reports, and documentation.
- Do not pause after every technical substep asking for permission; proceed, verify, and summarize.

## Workflow

1. Lock target scope before collecting data.
   - For the current football project: World Cup 2026 national-team matches.
   - Markets: 1X2, over/under 2.5, and betting value.
   - Training data: World Cup finals + World Cup qualifiers only.
   - Historical window: `2014-06-12` onward through data available before kickoff.

2. Import and validate data.
   - Use `scripts/import_matches.py` for public international results.
   - Verify date range, competition names, complete scores, and neutral venue fields.
   - Preserve source/provenance fields.

3. Run rolling backtests.
   - Use only prior matches to predict each match.
   - Avoid future-data leakage.
   - Save per-match predictions for later calibration analysis.

4. Calibrate model parameters.
   - Optimize log loss, not accuracy alone.
   - Current objective: `0.7 * log_loss_1x2 + 0.3 * log_loss_ou25`.
   - Save both the full grid and selected best parameters.

5. Analyze probability calibration.
   - Bin predicted probabilities and compare against observed frequencies.
   - Treat ECE and bucket errors as first-class outputs.
   - If a market is overconfident, add post-calibration or shrinkage before using it for value calls.

6. Update config and docs immediately.
   - `config/project.yaml` should carry current selected parameters and performance metrics.
   - `references/*.md` should explain why the parameter/model choice exists.
   - `SKILL.md` should point to new scripts, reports, and references.

## Current Football-Specific Lessons

- 1X2 is currently the primary value-betting input.
- O/U 2.5 needs post-calibration shrinkage and should be treated as a secondary signal.
- Current O/U shrinkage: `ou_base_rate=0.45`, `ou_shrinkage=0.45`.
- Do not promote a model-side edge to a betting recommendation without odds and overround normalization.

## Pitfalls

- Do not use raw accuracy as the main calibration target; it rewards overconfident but poorly priced probabilities.
- Do not mix friendlies, continental tournaments, or Nations League data into the current World Cup-only training universe unless the user explicitly changes scope.
- Do not treat O/U probability alone as a betting trigger before historical odds/ROI testing.
- Do not rerun slow full-history recalculation loops for every grid point if a rolling incremental update is sufficient.
