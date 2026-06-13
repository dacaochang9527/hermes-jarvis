# World Cup 2026 Data Pipeline

This reference captures the reusable pipeline for the current `football-predictor` project scope.

## Approved Scope

- Target: World Cup 2026 national-team matches.
- Markets: 1X2, over/under 2.5, and betting value when odds are available.
- Training competitions: `FIFA World Cup` and `FIFA World Cup qualification` only.
- Historical window: from `2014-06-12` onward, ending before the predicted match kickoff.
- Excluded by default: continental cups, continental qualifiers, Nations League, friendlies, Olympic/U23, `CONIFA World Cup qualification`, and `Viva World Cup`.

## Public Match Results Source

Primary source:

```txt
https://raw.githubusercontent.com/martj42/international_results/master/results.csv
```

Expected upstream columns:

```txt
date,home_team,away_team,home_score,away_score,tournament,city,country,neutral
```

The source includes similarly named non-target tournaments and rows with `NA` scores for unplayed/incomplete matches. Import logic must explicitly filter these out rather than relying on substring matching.

## Import Contract

The import script should:

1. Read the public CSV URL or a local CSV override.
2. Keep only rows with `date >= 2014-06-12`.
3. Keep only exact tournament names `FIFA World Cup` and `FIFA World Cup qualification`.
4. Skip rows where `home_score` or `away_score` is `NA`.
5. Normalize fields to the project schema: `date`, `home`, `away`, `home_goals`, `away_goals`, `competition`, `is_neutral`, `city`, `venue_country`, `source`.
6. Write both JSON and CSV mirrors under `data/`.

Current command from the skill directory:

```bash
python3 scripts/import_matches.py
```

Current outputs:

```txt
data/world_cup_matches_2014_onward.json
data/world_cup_matches_2014_onward.csv
```

## Validation Checklist

- Date range starts at or after `2014-06-12`.
- Competition set is exactly `FIFA World Cup` and `FIFA World Cup qualification`.
- All score fields are integers, not `NA`.
- Neutral venue is preserved as `is_neutral`.
- Data provenance is preserved in `source`.

## Next Build Step

After importing data, build a `backtest.py` workflow that walks chronologically through historical matches, trains only on prior matches, predicts the next match, and evaluates 1X2 / O-U calibration before trusting any betting-value output.
