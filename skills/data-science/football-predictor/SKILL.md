---
name: football-predictor
description: Build and run football match prediction models. Current baseline uses Poisson goals + team attack/defense ratings, with room for Elo, xG, market-odds, Dixon-Coles, and ML extensions.
version: 1.2.0
---

# Football Predictor

This skill is the single home for the football prediction project. Keep the runnable MVP, sample data, dependencies, model notes, and reference templates inside this skill directory.

Current baseline: Poisson goals × team attack/defense ratings. Treat Poisson as the first explainable model, not the final architecture.

## Trigger

When the user wants to:
- Build or run a football/soccer match prediction model
- Predict 1X2, over/under, BTTS, or exact scores
- Estimate team strength ratings from match history
- Compare Poisson with Elo, xG, betting-market, Dixon-Coles, or ML models
- Extend or debug the local football prediction MVP
- Consolidate football predictor code into Hermes skills

## Canonical Location

Skill directory:

```txt
/Users/fenomenoronaldo/.hermes/skills/data-science/football-predictor
```

Important files:

| Path | Purpose |
|------|---------|
| `scripts/football_types.py` | Shared lightweight data structures used by advanced mode |
| `scripts/model.py` | Legacy runnable Poisson baseline engine and rating estimator; requires numpy/scipy |
| `scripts/ratings.py` | Elo-style national-team strength rating layer |
| `scripts/goals.py` | Poisson + Dixon-Coles goal distribution layer |
| `scripts/post_calibration.py` | Post-model probability shrinkage/calibration helpers, currently used for O/U 2.5 |
| `scripts/signals.py` | Betting signal grading and discipline rules for 1X2 value and O/U lean |
| `scripts/value.py` | Betting-market implied probability and value layer |
| `scripts/import_matches.py` | Download/import public international results and filter to World Cup finals + qualifiers from 2014-06-12 onward |
| `scripts/backtest.py` | Rolling backtest for 1X2 and O/U 2.5 without future-data leakage |
| `scripts/calibrate.py` | Grid-search calibration over league average goals, home advantage, Dixon-Coles rho, and minimum training window |
| `scripts/analyze_calibration.py` | Probability calibration bin analysis for 1X2 and O/U 2.5 |
| `scripts/predict.py` | CLI entrypoint for baseline, advanced predictions, and demos |
| `config/project.yaml` | Machine-readable target, training scope, competition filters, and model route |
| `data/world_cup_matches_2014_onward.json` | Imported World Cup finals + qualifiers from 2014-06-12 onward for model training |
| `data/world_cup_matches_2014_onward.csv` | CSV mirror of imported training matches |
| `data/ratings.json` | Current sample/team ratings |
| `data/matches.json` | Match-history sample data for `--build` |
| `reports/backtest_predictions.csv` | Generated rolling-backtest predictions and actual outcomes |
| `reports/calibration_results.csv` | Calibration grid results sorted by combined log-loss score |
| `reports/calibration_best.json` | Selected calibrated parameter set |
| `reports/probability_calibration_bins.csv` | Probability bucket calibration details for 1X2 and O/U 2.5 |
| `reports/probability_calibration_report.md` | Human-readable probability calibration report |
| `references/requirements.txt` | Runtime Python dependencies |
| `references/model-template.py` | Clean reference implementation template |
| `references/backtesting.md` | Rolling-backtest method, command, metrics, and limitations |
| `references/calibration.md` | Calibration command, objective, selected parameters, and current backtest result |
| `references/probability-calibration.md` | Probability calibration method, current ECE, bucket errors, and modeling implications |
| `references/betting-signal-discipline.md` | Signal grades and betting discipline for 1X2 value and O/U lean |
| `references/world-cup-2026-model-iteration.md` | Current World Cup 2026 modeling workflow, calibrated parameters, performance snapshot, and autonomous iteration preference |
| `references/model-calibration-workflow.md` | Durable workflow for scope locking, data import, rolling backtest, parameter calibration, and probability calibration |
| `references/world-cup-2026-model-evolution.md` | Reusable workflow for user-decision-first scope locking, data import, backtesting, calibration, and next-step probability calibration |
| `references/world-cup-2026-data-pipeline.md` | Reusable data source, import, filtering, and validation pipeline for the approved World Cup 2026 scope |
| `references/data-sources.md` | Public data source, import command, and validation expectations |
| `references/world-cup-2026-scope.md` | User-approved target scope: World Cup 2026, 1X2/O-U/value, and World Cup finals + qualifiers only |
| `references/data-schema.md` | Data schema for World Cup 2026 match history, rankings, and odds |
| `references/world-cup-value-modeling.md` | User-targeted World Cup/national-team 1X2, O/U, and value-betting modeling notes |
| `references/consolidating-standalone-projects.md` | How to absorb a standalone predictor project into this skill |

## Run Commands

From the skill directory:

```bash
python3 scripts/predict.py --sample
python3 scripts/predict.py "Mexico" "South Africa"
python3 scripts/predict.py "Mexico" "South Africa" --build
python3 scripts/predict.py "Mexico" "South Africa" --advanced
python3 scripts/predict.py "Mexico" "South Africa" --advanced --odds-1x2 1.80 3.40 4.80
```

If dependencies are missing:

```bash
python3 -m pip install -r references/requirements.txt
```

## Poisson Baseline

The Poisson model assumes each team's goal count is a random variable whose average goal expectation is `λ`.

```txt
λ_home = league_avg × home_attack × away_defense × home_advantage
λ_away = league_avg × away_attack × home_defense
```

Score probability matrix:

```txt
P(home=i, away=j) = Poisson(i|λ_home) × Poisson(j|λ_away)
```

From the matrix, sum over cells to get:
- 1X2: sum P(i>j), P(i=j), P(i<j)
- Over/Under: sum P(i+j > line), P(i+j ≤ line)
- BTTS: sum P(i>0 ∧ j>0), P(¬both_score)
- Top exact scores: sort by probability, take top N

## Output Dimensions

| Dimension | Description |
|-----------|-------------|
| 1X2 | Home win / Draw / Away win probabilities |
| Over/Under | Total goals above/below a line, default 2.5 |
| BTTS | Both Teams To Score — Yes/No |
| Exact score Top N | Most likely scorelines with probabilities |
| xG | Expected goals for each side, the λ values |

## Model Roadmap

Current user target: World Cup 2026 national-team matches, focused on 1X2, over/under, and betting value. Training scope is limited to World Cup finals + World Cup qualifiers from 2014-06-12 onward; continental cups, Nations League, and friendlies are excluded by default. Available data starts with historical scores + rankings, with odds used as reference. Default advanced route: Elo-style team strength → Poisson/Dixon-Coles goal distribution → 1X2/O-U probabilities → compare against market odds for value.

| Model | Useful For | Notes |
|-------|------------|-------|
| Poisson baseline | Exact score, O/U, BTTS | Explainable and easy to calibrate, but assumes independent goals |
| Dixon-Coles | Low-score football matches | Poisson extension that adjusts 0-0, 1-0, 0-1, 1-1 dependence |
| Elo/SPI-style ratings | Team strength trend | Good for long-term strength, needs mapping to goals/probabilities |
| xG-based model | More signal than raw goals | Better if shot/xG data is available |
| Betting-market model | Realistic probability baseline | Odds embed crowd/market information; useful for calibration and value detection |
| Gradient boosting / ML | Feature-rich prediction | Needs larger clean dataset; less transparent than Poisson |
| Bayesian hierarchical model | Sparse leagues/teams | Shrinks noisy teams toward league priors; good when data is limited |

## Two Modes For Team Ratings

### Mode 1: Hand-Crafted Ratings

Define `TeamRating(name, attack, defense)` directly. Attack > 1 means above-average scoring. Defense < 1 means tighter defense as a multiplier on opponent goals. This mode is best for MVP work or low-data situations.

### Mode 2: Data-Driven Estimation

Iterative MLE alternates updating attack and defense until convergence:

```txt
For each team t:
  attack[t]  = total_goals_scored_by_t / Σ(league_avg × opponent_defense × [home_adv if t was home else 1])
  defense[t] = total_goals_conceded_by_t / Σ(league_avg × opponent_attack × [home_adv if opponent was home else 1])
```

Repeat until max change < tolerance.

## Maintenance Rules

- Treat this skill as the canonical source for the football predictor.
- Put runnable code in `scripts/`, sample or working data in `data/`, and explanatory/dependency files in `references/`.
- Do not re-create or continue editing `/Users/fenomenoronaldo/football-predictor` unless the user explicitly asks for a standalone export.
- Keep `references/model-template.py` as a clean starter template; put project-specific behavior in `scripts/model.py` and `scripts/predict.py`.
- If the model expands beyond Poisson, keep Poisson as a baseline and add new modules under `scripts/` rather than replacing the only working path.
- For World Cup prediction requests, interpret user-stated dates such as "today", "tomorrow", or `6月14日` as Beijing time (`Asia/Shanghai`) unless the user explicitly says local venue time.
- For the current World Cup 2026 project scope, do not import continental cups, Nations League, friendlies, or youth/Olympic matches unless the user explicitly changes the training scope.
- For iterative model-building work in this skill, proceed autonomously on obvious next engineering steps: add scripts, run backtests, calibrate parameters, update reports, and sync documentation without asking first. Ask the user only when the decision changes goals, scope, data universe, risk tolerance, or tradeoff priorities.

## Pitfalls

### 1. Wrong Iterative Update Formula Causes ZeroDivisionError

Do not use `lam / rating` in the denominator. It is fragile when ratings fluctuate. Use the direct form: `league_avg × opposite_rating × home_adv_factor`. No division by the rating being updated.

### 2. Sparse Data Produces Extreme Ratings

With fewer than 30-50 matches per team, MLE estimates can hit 0.0 or 2.0+. This is expected overfit. Use hand-crafted ratings, add regularization, or collect more data before trusting `--build` output.

### 3. Display Label Uses Wrong Variable

When displaying over/under, use a fixed line label like `大2.5`, not `f"大{p.over25}"`; `over25` is the probability, not the line value.

## Verification Checklist

- `python3 scripts/predict.py --sample` runs from the skill directory.
- `python3 scripts/predict.py "Mexico" "South Africa"` reads `data/ratings.json`.
- `python3 scripts/predict.py "Mexico" "South Africa" --build` reads `data/matches.json`.
- No separate `~/football-predictor` source copy is treated as canonical.
