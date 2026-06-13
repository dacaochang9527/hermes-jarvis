# World Cup 2026 Prediction Scope

This reference captures the current user-approved operating scope for the `football-predictor` skill.

## User Goal

Predict World Cup 2026 national-team matches with emphasis on:

- 1X2: home/listed-first win, draw, away/listed-second win
- Over/Under 2.5 goals
- Betting value, when market odds are available

Preferred output shape:

- A clear model conclusion
- Probability table
- Whether the market price is worth betting or should be skipped

## Approved Training Scope

Use only:

- World Cup finals
- World Cup qualifiers

Exclude by default:

- Continental cup finals, such as Euro, Copa América, Asian Cup, AFCON
- Continental qualifiers
- Nations League competitions
- International friendlies
- Olympic/U23 matches

The reason is consistency with the target event. The user chose a narrower, more relevant training universe over a larger but noisier national-team sample.

## Current Model Route

Default route for this scope:

1. Elo-style national-team strength layer from historical World Cup finals/qualifiers.
2. Poisson + Dixon-Coles goal-distribution layer for 1X2, totals, BTTS, and likely scores.
3. Market-implied probability layer when odds are provided.
4. Value judgment from model probability minus normalized market probability.

Do not treat a model-side edge as a betting recommendation until odds are present and overround is normalized.

## Approved Historical Window

Use the last three World Cup cycles:

- Start date: `2014-06-12`, the opening day of the 2014 World Cup.
- End policy: use only data available before the kickoff of the match being predicted.
- Included competitions within this window: World Cup finals and World Cup qualifiers only.

This covers the 2014, 2018, and 2022 World Cup cycles plus the current 2026 qualifying cycle, while avoiding older teams whose strength is no longer representative.
