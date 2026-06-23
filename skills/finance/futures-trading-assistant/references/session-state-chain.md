# Futures Session State Chain

Use this reference whenever producing PVC2609 or other Chinese futures review/forecast reports, especially day/night session handoff.

## Mandatory report chain

The workflow is a two-document rolling chain, not four isolated files.

1. Day close document: `reports/{contract}_{YYYYMMDD}_day_review_night_plan.md`
   - Contains the completed day-session review.
   - Contains the same natural day's night-session forecast/operation plan.
   - Must explicitly say that the night plan inherits the day review.
   - Replaces separate `*_day_review.md` + `*_night_plan.md` for new reports unless the user explicitly requests separate files.

2. Night close document: `reports/{contract}_{YYYYMMDD}_night_review_next_day_plan.md`
   - Contains the completed night-session review.
   - Contains the next day-session forecast/operation plan.
   - Must explicitly state natural-day night session and trading-day attribution when relevant.
   - Must read the latest day close document first, then the actual night-session data, before writing the next day plan.
   - Replaces separate `*_night_review.md` + `*_next_day_plan.md` for new reports unless the user explicitly requests separate files.

## Required inputs

Before creating a day close document:

- Read the prior forecast/plan that governed the day session.
- Fetch/verify day-session quote and 3m/15m/30m/60m/120m/daily K-lines when available.
- Read local monitor logs for actual alerts and briefing levels.
- If user trade screenshots are expected, wait for them before publishing execution review.

Before creating a night close document:

- Read the same day's `day_review_night_plan` document.
- Fetch/verify night-session K-lines and quote snapshot.
- Read local monitor logs covering 21:00-23:00.
- Treat the night session as the first input to the next day-session plan, not as an optional note.

## Mandatory forecast-vs-actual review table

Every review section must evaluate each prior plan/scenario individually. Use a table like:

| Prior plan/scenario | Planned trigger | Actual path | Match? | Why matched / why not | Execution implication |
|---|---|---|---|---|---|
| A: 反抽承压空 | 4470-4480 承压、3m转弱 | ... | 相符/部分相符/不相符/未触发 | ... | ... |

Rules:

- Do not only say “方向对/错”. Explain trigger quality, timing, volume/open-interest confirmation, and whether the scenario was invalidated.
- Include scenarios that did not trigger. “未触发” is a valid review result and prevents hindsight bias.
- Separate “market matched the plan” from “user execution quality” when user trades are included.
- If public data lacks tick/active-buy detail, say so instead of inferring 主动买卖.

## State handoff fields

At the end of each combined document, include a machine-readable-ish handoff block in plain Markdown:

```text
STATE_HANDOFF
contract: PVC2609
source_doc: reports/...
session_completed: day|night
next_session: night|next_day_day
bias: bearish|neutral|bullish|range|repair
risk_flags: extreme_oversold, low_chase_risk, range_trap
must_watch_levels:
  - price: 4439-4440
    role: support
    label: 日盘低点/首要防守
    trigger: break_down_or_reclaim
  - price: 4470-4480
    role: resistance
    label: 反抽承压区
    trigger: rejection_or_reclaim
invalidated_levels:
  - price: 4550
    reason: 已远离当前主战场，不再作为核心提醒
monitor_levels_updated: yes|no
```

This block is for human + agent continuity. It is not guaranteed to be parsed automatically unless also written to the runtime JSON file below.

## Monitor level synchronization

Whenever a new forecast/operation plan is finalized, update:

`runtime/pvc2609_feishu_monitor/latest_prediction_levels.json`

Schema:

```json
{
  "contract": "PVC2609",
  "source_doc": "reports/pvc2609_YYYYMMDD_day_review_night_plan.md",
  "updated_at": "2026-06-23T20:50:00+08:00",
  "session": "night",
  "levels": [
    {"price": 4440, "role": "support", "label": "日盘低点/首要防守", "direction": "both"},
    {"price": 4470, "role": "resistance", "label": "反抽承压区下沿", "direction": "both"},
    {"price": 4480, "role": "resistance", "label": "反抽承压区上沿", "direction": "both"},
    {"price": 4490, "role": "invalidation_short", "label": "空头优势降级位", "direction": "up"}
  ]
}
```

Runtime monitors read this file on every cron tick. If the file is missing or invalid, monitors fall back to dynamic K-line support/resistance only and should not use stale hardcoded levels.

## Practical interpretation

- Day session affects same-day night plan through day high/low/close, volume/open-interest, confirmed/failed levels, and risk flags such as overbought/oversold.
- Night session affects next day plan as the latest price-discovery segment. The next day plan must start from whether night trading confirmed, rejected, reclaimed, or invalidated day-session levels.
- Do not carry levels forward indefinitely. Each plan must mark which previous levels remain active, downgraded, or invalidated.
