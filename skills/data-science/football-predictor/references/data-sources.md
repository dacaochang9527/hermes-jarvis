# Football Predictor Data Sources

## Primary Match Results Source

Use the public `martj42/international_results` dataset as the initial historical match-results source.

Source URL:

```txt
https://raw.githubusercontent.com/martj42/international_results/master/results.csv
```

Repository:

```txt
https://github.com/martj42/international_results
```

Available columns:

```txt
date, home_team, away_team, home_score, away_score, tournament, city, country, neutral
```

## Current Import Scope

For the World Cup 2026 project, import only:

- `FIFA World Cup`
- `FIFA World Cup qualification`

From:

- `2014-06-12` onward

Explicitly exclude similarly named but non-target competitions:

- `CONIFA World Cup qualification`
- `Viva World Cup`
- Friendlies
- Continental tournaments
- Nations League
- Olympic/U23 matches

## Import Command

From the skill directory:

```bash
python3 scripts/import_matches.py
```

Outputs:

```txt
data/world_cup_matches_2014_onward.json
data/world_cup_matches_2014_onward.csv
```

Use a local CSV instead of the URL:

```bash
python3 scripts/import_matches.py --source /path/to/results.csv
```

## Validation Expectations

After import, verify:

- Date range starts at or after `2014-06-12`.
- Tournament counts only include `FIFA World Cup` and `FIFA World Cup qualification`.
- The source field is preserved for provenance.
- Neutral venue is retained as `is_neutral`.
