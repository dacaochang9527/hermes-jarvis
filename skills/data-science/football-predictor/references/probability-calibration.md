# Probability Calibration Analysis

## Purpose

Probability calibration checks whether the model's stated probability matches historical frequency. This matters for betting value: a 60% model probability is only useful if similar 60% predictions have historically won close to 60% of the time.

## Command

From the skill directory, first regenerate backtest predictions with the selected calibrated parameters:

```bash
python3 scripts/backtest.py --league-avg 1.35 --home-adv 1.12 --rho=-0.04 --min-training-matches 300
```

Then run:

```bash
python3 scripts/analyze_calibration.py
```

Outputs:

```txt
reports/probability_calibration_bins.csv
reports/probability_calibration_report.md
```

## Current Result

O/U probabilities now use post-calibration shrinkage toward the historical over-2.5 base rate:

| Parameter | Value |
|-----------|-------|
| `ou_base_rate` | `0.45` |
| `ou_shrinkage` | `0.45` |

| Market | Expected Calibration Error |
|--------|-----------------------------|
| `1X2` | `0.047` |
| `OU25` | `0.057` |

Interpretation:

- `1X2` probabilities are usable as the primary value-betting baseline, though away favorites remain somewhat overconfident in the 70-80% bucket.
- `OU25` improved materially after shrinkage: ECE moved from `0.103` to `0.057`, and O/U log loss moved from `0.7065` to `0.6805`.
- O/U is now acceptable as a secondary signal, but still should be weighted below 1X2 until a dedicated totals model or historical odds ROI check is added.

Largest current bucket issues:

| Bucket | Avg Pred | Observed | Error | Count |
|--------|----------|----------|-------|-------|
| `OU25/over 0.2-0.3` | `24.3%` | `53.3%` | `+29.1%` | `30` |
| `OU25/under 0.7-0.8` | `75.7%` | `46.7%` | `-29.1%` | `30` |
| `1X2/away 0.7-0.8` | `75.0%` | `58.8%` | `-16.2%` | `153` |
| `OU25/over 0.3-0.4` | `36.4%` | `50.0%` | `+13.6%` | `116` |
| `OU25/under 0.6-0.7` | `63.6%` | `50.0%` | `-13.6%` | `116` |

## Modeling Consequence

For now:

- Treat 1X2 probabilities as the primary value-betting input.
- Treat O/U 2.5 as a secondary signal after shrinkage, not as a standalone betting trigger.
- Avoid betting decisions based on O/U alone until historical odds/ROI are available.

## Next Improvement Ideas

1. Add a dedicated totals model using recent team scoring/conceding distribution.
2. Add historical odds to test whether calibrated edges translate into ROI.
3. Calibrate 1X2 away-favorite probabilities separately if this bias persists with odds data.
4. Add confidence labels that distinguish primary `1X2 value` from secondary `O/U lean`.
