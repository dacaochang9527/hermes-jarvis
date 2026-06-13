# Football Predictor Backtesting

## Purpose

Backtesting checks whether the current model route is useful before trusting any betting-value output.

Current scope:

- Target: World Cup 2026 national-team matches
- Training data: World Cup finals + World Cup qualifiers only
- Historical window: from `2014-06-12` onward
- Evaluation markets: 1X2 and over/under 2.5

## Command

From the skill directory:

```bash
python3 scripts/backtest.py
```

Default input:

```txt
data/world_cup_matches_2014_onward.json
```

Default output:

```txt
reports/backtest_predictions.csv
```

## Method

The script performs a rolling backtest:

1. Sort matches chronologically.
2. Skip early matches until `--min-training-matches` history exists.
3. For each match, train Elo/goal priors only on previous matches.
4. Predict the current match with Elo → Poisson/Dixon-Coles.
5. Record 1X2, O/U 2.5 probabilities, xG, Elo, and actual result.
6. Update evaluation metrics across all predicted matches.

This avoids future-data leakage.

## Metrics

| Metric | Meaning |
|--------|---------|
| `1X2 accuracy` | Whether the highest-probability 1X2 pick matched the result |
| `O/U 2.5 accuracy` | Whether the model's over/under side matched total goals |
| `1X2 log loss` | Probability quality for the actual 1X2 result; lower is better |
| `O/U 2.5 log loss` | Probability quality for the actual total-goals side; lower is better |

## Limitations

- No historical odds are included yet, so betting ROI is not evaluated.
- Accuracy alone is not enough for betting; value requires comparing model probability against market probability.
- Current goal priors are simple and should be calibrated after seeing backtest output.
- World Cup finals are upweighted in a simple dependency-free way; this can be refined later.
