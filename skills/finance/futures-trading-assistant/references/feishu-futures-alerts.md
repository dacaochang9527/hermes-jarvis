# Futures Feishu Alert Design

Use this reference when turning futures analysis into Feishu group notifications.

## Stakeholder Intent Pattern

When a user or trading group asks for futures alerts, distinguish these two modes explicitly:

- **Point-triggered operation alerts**: send only when price reaches a configured key level and fresh volume, K-line shape, and indicators confirm a break, reclaim, rejection, stop-loss, or take-profit condition.
- **Fixed-interval simplified briefings**: send every configured interval, commonly 30 minutes, with trend, nearest levels, and structure notes, but no direct operation advice unless the user explicitly requests it.

If the group discusses “多空交战区”, “横盘陷阱”, or repeated price crossing around the same level, treat this as a chop/noise-control requirement: suppress repeated trade alerts, switch wording to observe/range-trap, and wait for a confirmed break/reclaim or failed retest before pushing another operation alert.

## Required Alert Fields

Every pushed alert should contain:

- Contract symbol, e.g. `PVC2609`.
- Quote timestamp and alert timestamp.
- Data freshness: live / stale / delayed.
- Current price and key comparison: near support, resistance, stop-loss, or target.
- Trigger reason in one sentence.
- Action state: observe, possible long, possible short, invalidated, stop-loss, take-profit, risk reminder.
- Key levels: entry zone, stop loss, target zone, invalidation.
- Data caveat when public feeds lack five-level order book or tick-by-tick active buy/sell.
- Group mention prefix: scheduled Feishu group pushes should include `@所有人` as the first line of the message template unless the user explicitly requests a quiet push.

## Trigger Levels

Use event triggers, not every tick:

- Break above resistance and hold through one completed 3m bar.
- Break below support and fail to reclaim through one completed 3m bar.
- Break through manually curated scenario levels from group analysis, such as prior settlement, prior-day low, or named support/resistance zones; keep these as explicit key levels instead of hiding them inside dynamic support/resistance calculations.
- Retest failure after break/reclaim.
- Touch stop-loss / invalidation / take-profit.
- 3m and 15m structures align after prior conflict.
- Volume expansion plus open-interest delta confirms or warns about the move.
- Pre-close or night-session risk reminder when a position plan exists.

## Severity

- A-level: stop-loss, invalidation, key break, sharp move, take-profit. Send immediately.
- B-level: entry-zone approach, structure alignment, volume/open-interest confirmation. Send with cooldown.
- C-level: routine quote state, minor oscillation, unchanged trend. Log locally; do not push.

## Frequency Control

Recommended default:

- Poll quote snapshot every 1 minute during trading sessions.
- Recalculate 3m signals every 3 minutes.
- Recalculate 15m signals every 15 minutes.
- Cool down same contract + direction + level for 5-10 minutes.
- De-duplicate until price leaves and re-enters the trigger zone.
- Do not send non-trading stale-data alerts unless producing a planned report.

## Example Message

```text
PVC2609｜09:36｜现价 4628｜行情实时
触发：站回 4625，3m 收稳，15m 动能修复
计划：回踩 4620-4625 不破可观察多单
风控：止损 4595；目标 4660/4675；失效：跌回 4610 下方
备注：公开数据仅一档盘口，无逐笔主动买卖
```
