# Football Predictor Data Schema

Target: World Cup 2026 national-team prediction, focused on 1X2, over/under, and betting value.

## Match History Schema

Use this schema for historical national-team matches. For the current World Cup 2026 model, include only World Cup finals and World Cup qualifiers from `2014-06-12` onward, using only data available before the predicted match kickoff. CSV is preferred for collection; JSON is acceptable for the current scripts.

Required fields:

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `date` | `YYYY-MM-DD` | `2024-06-20` | Chronological Elo updates and recency weighting |
| `home` | string | `Argentina` | Home or listed first team |
| `away` | string | `Canada` | Away or listed second team |
| `home_goals` | integer | `2` | Final-score home goals |
| `away_goals` | integer | `0` | Final-score away goals |
| `competition` | string | `World Cup Qualifier` | Competition weighting |
| `is_neutral` | boolean | `true` | Disable or reduce home advantage |

Recommended fields:

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `stage` | string | `group` | Group/knockout/friendly handling |
| `confederation` | string | `CONMEBOL` | Regional strength context |
| `venue_country` | string | `USA` | Host/neutral inference |
| `source` | string | `manual` | Data provenance |

## Ranking Schema

Use rankings as initial team-strength priors, not as direct match predictions.

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `date` | `YYYY-MM-DD` | `2026-05-01` | Ranking snapshot date |
| `team` | string | `France` | Team name |
| `rank` | integer | `2` | FIFA rank or custom rank |
| `points` | float | `1850.00` | Optional rating points |
| `source` | string | `FIFA` | Ranking source |

## Odds Schema

Odds are required for value-betting decisions. Without odds, output direction only.

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `match_id` | string | `2026-06-11_mexico_south-africa` | Join key |
| `bookmaker` | string | `market_avg` | Odds source |
| `snapshot_time` | ISO datetime | `2026-06-10T20:00:00+08:00` | Line movement tracking |
| `home_odds` | decimal | `1.80` | 1X2 home win odds |
| `draw_odds` | decimal | `3.40` | 1X2 draw odds |
| `away_odds` | decimal | `4.80` | 1X2 away win odds |
| `over25_odds` | decimal | `2.05` | Optional O/U value check |
| `under25_odds` | decimal | `1.82` | Optional O/U value check |

## Competition Scope And Weights

Current training scope for World Cup 2026 prediction:

| Competition Type | Include | Weight |
|------------------|---------|--------|
| World Cup finals | yes | `1.25` |
| World Cup qualifiers | yes | `1.00` |
| Continental finals | no | excluded |
| Continental qualifiers | no | excluded |
| Nations League | no | excluded |
| Friendly | no | excluded |

## Modeling Notes

- World Cup 2026 target matches should be predicted from data available before kickoff only.
- Training data includes only World Cup finals and World Cup qualifiers by default.
- Continental cups, continental qualifiers, Nations League, and friendlies are excluded unless the user explicitly changes scope.
- Neutral venue must be explicit; World Cup finals are usually neutral except host matches.
- Rankings should initialize or regularize Elo, not replace match-history performance.
- Betting value requires comparing model probability against market-implied probability after overround normalization.
