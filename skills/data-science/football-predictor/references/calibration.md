# Football Predictor Calibration

## Purpose

Calibration chooses model parameters by out-of-sample rolling backtest performance, using log loss rather than accuracy alone.

Current target:

- World Cup 2026 national-team matches
- Training scope: World Cup finals + World Cup qualifiers from `2014-06-12` onward
- Prediction markets: 1X2 and over/under 2.5

## Command

From the skill directory:

```bash
python3 scripts/calibrate.py --league-avgs 1.05,1.15,1.25,1.35 --home-advs 1.00,1.04,1.08,1.12 --rhos=-0.12,-0.08,-0.04,0.00 --min-training 100,300
```

Outputs:

```txt
reports/calibration_results.csv
reports/calibration_best.json
```

## Objective

Primary objective:

```txt
score = 0.7 * log_loss_1x2 + 0.3 * log_loss_ou25
```

This prioritizes 1X2 because the user cares about win/draw/loss and betting value, while still penalizing poor totals calibration.

## Current Selected Parameters

| Parameter | Value |
|-----------|-------|
| `league_avg` | `1.35` |
| `home_advantage` | `1.12` |
| `dixon_coles_rho` | `-0.04` |
| `ou_base_rate` | `0.45` |
| `ou_shrinkage` | `0.45` |
| `min_training_matches` | `300` |

## Selected Backtest Result

| Metric | Value |
|--------|-------|
| Backtested matches | `2514` |
| 1X2 accuracy | `58.6%` |
| O/U 2.5 accuracy | `56.2%` |
| 1X2 log loss | `0.8956` |
| O/U 2.5 log loss | `0.6805` |
| 1X2 ECE | `0.047` |
| O/U 2.5 ECE | `0.057` |
| Combined score | `0.8311` |

## Notes

- Calibration currently does not include historical odds, so it optimizes prediction quality, not betting ROI.
- The selected parameters should be treated as baseline-calibrated, not final.
- Next calibration layer should test Elo K-factor, Elo home advantage, tournament weight, and probability calibration bins.
