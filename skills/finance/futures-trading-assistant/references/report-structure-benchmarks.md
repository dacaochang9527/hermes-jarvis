# Futures Report Structure Benchmarks

This reference captures reusable report-format lessons from reviewing an external AI-generated PVC2609 analysis page. Treat such pages as structure benchmarks, not verified market sources.

## What to borrow

1. Add a time-slice forecast-vs-actual table in addition to scenario validation.

Suggested columns:

| Review dimension | Prior forecast | Actual path | Match status | Deviation reason | Next adjustment |
|---|---|---|---|---|---|
| Open | ... | ... | ... | ... | ... |
| First 30 minutes | ... | ... | ... | ... | ... |
| Main session | ... | ... | ... | ... | ... |
| Tail/close | ... | ... | ... | ... | ... |
| Range/volatility | ... | ... | ... | ... | ... |

2. Add an error/logic-adjustment table after each meaningful review.

Suggested columns:

| Issue type | This-session evidence | Consequence | Future rule |
|---|---|---|---|
| Trend inertia underestimated | ... | ... | ... |
| Oversold signal over-weighted | ... | ... | ... |
| Key-level confirmation missed | ... | ... | ... |
| Timeframe mismatch | ... | ... | ... |
| Execution granularity too fine | ... | ... | ... |

3. Use a top-down multi-timeframe structure table for plans.

Preferred order: weekly/daily -> 120m/60m -> 30m/15m -> 3m -> quote/position. This prevents 3m signals from overriding the higher-timeframe context.

Suggested columns:

| Timeframe | Direction/structure | Key levels | Indicator state | Trading implication |
|---|---|---|---|---|

4. Include small-account point reality when the user mentions account size, recent loss, or target return.

Suggested columns:

| Target P&L | Points needed with 1 lot | Points needed with 2 lots | Current-market feasibility | Suggested posture |
|---|---:|---:|---|---|

Frame this as risk feasibility, not a promise to achieve the target.

## What not to borrow blindly

- Do not treat AI share pages as authoritative data sources. Use them as prompts for structure or hypotheses only.
- Do not copy unverified industry-news claims unless the original source is opened and timestamped.
- Do not infer active buy/sell, 多开/空开/多平/空平 from public K-lines. Only use screenshot-visible fields if available, and label them as screenshot-derived.
- Avoid deterministic language such as “盈利 5% 方案” or fixed statistical-sounding win rates. Prefer conditional triggers and probability ranges with caveats.
- Do not use 缠论 terms unless the report actually constructs 分型、笔、线段、中枢 and explains the derivation.

## Recommended upgraded report order

1. One-sentence conclusion.
2. Data state and limitations.
3. Top-down multi-timeframe structure table.
4. Prior plan vs actual validation:
   - scenario validation table;
   - time-slice validation table.
5. Hit/miss attribution and logic-adjustment table.
6. Key-level change table: retained, shifted, invalidated.
7. Next-session scenario probability table with triggers and invalidation.
8. Operation plan tables for long, short, breakdown/reversal, and observe.
9. Small-account point/risk feasibility table when relevant.
10. STATE_HANDOFF block and monitor-level synchronization note.
