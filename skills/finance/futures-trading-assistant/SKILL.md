---
name: futures-trading-assistant
description: "Use when analyzing Chinese futures contracts such as PVC2609: fetch public quote/K-line data, build multi-timeframe trading plans, monitor trigger levels, and save futures analysis reports."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [futures, trading, pvc, market-data, risk-management]
    related_skills: [research-workflows]
---

# Futures Trading Assistant

## Overview

This skill handles futures-specific analysis and monitoring tasks, especially Chinese commodity futures such as PVC2609.

The goal is to produce conditional trading plans, not deterministic investment advice. Futures are leveraged instruments; every output must include invalidation levels, stop-loss logic, position sizing, and a clear statement of data limitations.

## When to Use

Use this skill when the user asks for:

- Analysis of futures contracts such as PVC2609, RB, MA, FG, TA, etc.
- Intraday futures operation plans: long/short direction, entry, stop loss, take profit, probabilities.
- Multi-timeframe futures analysis using盘口、3分、15分、30分、60分、120分、日K.
- Futures quote/K-line data collection from public interfaces.
- Monitoring key futures levels and deciding whether a trigger condition is met.
- Sending futures alerts to Feishu groups when configured triggers fire.
- Saving futures analysis to Markdown reports.

Do not use this skill for:

- Guaranteed profit claims.
- Instructions to trade without conditions.
- Analyses that require tick-by-tick order flow when no tick data or screenshot is available.

## Public Data Sources

The current proven public sources for PVC2609 are documented in `references/china-futures-public-data.md`.

Feishu group alert rules and message templates are documented in `references/feishu-futures-alerts.md`.

Trading-session changes for Feishu futures monitors, including day + night cron/script/config alignment, are documented in `references/feishu-trading-session-updates.md`.

Pre-open guard check design is documented in `references/preopen-guard-checks.md`.

PVC monitor troubleshooting patterns for cron wrappers, Sina quote fallback, bad-state cleanup, and manual scenario-level promotion are documented in `references/pvc-monitor-troubleshooting.md`.

The current PVC2609 Feishu monitor configuration is `configs/pvc2609_feishu_monitor.yaml`.

Current PVC2609 cron scripts:

- `pvc2609_preopen_guard.py`: no-agent pre-open guard; runs at 08:50 on trading days and prints a Feishu-ready readiness report covering config, cron registration, quote/K-line availability, and local state-file sanity.
- `pvc2609_event_monitor.py`: no-agent event monitor; runs frequently during trading hours and prints only when an event should be pushed.
- `pvc2609_half_hour_briefing.py`: no-agent briefing monitor; cron may run every 5 minutes, but the script enforces an approximately 25-30 minute send cooldown during trading sessions.

For PVC2609, use:

- Real-time/quote snapshot: `https://hq.sinajs.cn/list=nf_V2609`
- Minute K-lines: `InnerFuturesNewService.getFewMinLine?symbol=V2609&type=3/15/30/60/120`
- Daily K-line: `InnerFuturesNewService.getDailyKLine?symbol=V2609`

Known limitations:

- Public quote snapshot provides only one-level bid/ask, not full five-level order book.
- Minute and daily K-lines include OHLC, volume `v`, and open interest `p`.
- Open interest change can be calculated from adjacent `p`, but cannot directly distinguish 多开、空开、多平、空平.
- Public interfaces checked so far do not provide reliable tick-by-tick active buy/sell or big-order classification.

## Default Analysis Workflow

1. Confirm date, trading day, and whether the market is open.
2. Fetch quote snapshot and verify the returned date/time; if stale, label it as stale.
3. Fetch 3m, 15m, 30m, 60m, 120m, and daily K-lines when available.
4. Compute at minimum:
   - last price / close, high, low, settlement if available;
   - recent support and resistance;
   - MA5/MA10/MA20 on daily;
   - MACD/RSI or equivalent momentum checks;
   - volume expansion/contraction;
   - open-interest changes from `p`.
5. Build scenarios rather than one unconditional instruction:
   - support holds → possible long;
   - resistance fails → possible short;
   - support breaks and retest fails → possible breakdown short;
   - no trigger → observe.
6. For every scenario, include entry zone, stop loss, take profit, estimated probability, basis, invalidation condition, and position-size caveat.
7. If saving to Markdown, write under `~/.hermes/skills/finance/futures-trading-assistant/reports/` unless the user specifies another path.

## Local Report ↔ Feishu Document Workflow

When the user asks to save a futures report and make it available in Feishu, treat the workflow as a three-step closed loop:

1. First save the canonical Markdown report under `~/.hermes/skills/finance/futures-trading-assistant/reports/` with a stable filename such as `{contract}_{YYYYMMDD}_{session_or_purpose}.md`.
2. Create the Feishu online document from that local Markdown using the Hermes Agent Feishu bot-owned document workflow. Use the official Feishu Markdown-to-docx block converter rather than hand-built Markdown blocks, so headings, tables, and lists render correctly.
3. After the Feishu document is created and its final URL is known, immediately patch the local Markdown metadata block near the top with a line like `> 飞书在线文档：https://...`.
4. If the Feishu document is later copied/recreated/retitled and the URL changes, patch the local Markdown link to the final retained URL and delete or ignore superseded URLs.
5. Only then send the final Feishu document link to the group when the user asks for group delivery.

This keeps the local report as the durable source of truth while preserving a direct pointer to the online Feishu version.

## Feishu Alert Workflow

When the user asks to notify futures information to a Feishu group, design the monitor as event-driven alerts rather than fixed chatty updates.

Required alert content:

- Contract, quote timestamp, and alert timestamp.
- Current price and whether the data is live or stale.
- Trigger reason, such as key-level break, reclaim, rejection, stop-loss, or take-profit.
- Key levels: support, resistance, invalidation, stop loss, and target zone.
- Scenario label: observe, long setup, short setup, breakdown, reversal, stop-loss, or take-profit.
- Risk wording: conditional language only; no guaranteed profit or forced trade instruction.
- Data limitations: mention one-level盘口 / no tick-by-tick active buy-sell when relevant.

Default trigger classes:

- Price triggers: effective break/reclaim of support or resistance, preferably confirmed by one completed 3m bar.
- Structure triggers: 3m and 15m direction alignment, failed retest, intraday high/low break, or 15m trend turn.
- Volume/open-interest triggers: volume expansion with price movement, abnormal open-interest delta, or non-confirmation warnings.
- Risk triggers: stop-loss, invalidation, take-profit, near close / night-session risk reminder.

Default frequency controls:

- Poll quote snapshot every 1 minute during trading sessions.
- Re-evaluate 3m structure every 3 minutes and 15m structure every 15 minutes.
- Do not push routine C-level state updates; write them locally if needed.
- Push A-level risk events immediately: stop-loss, invalidation, key break, sharp move.
- Push B-level setup events with a 5-10 minute cooldown per contract + direction + trigger level.
- De-duplicate the same trigger until price leaves and re-enters the trigger zone.

For the current Feishu group setup, the verified group target is `feishu:oc_3b94cfb91274b70374954d7b12f12432`. This is an environment-specific detail; confirm with the user or target list before relying on it in a different setup.

## PVC2609 Working Levels Pattern

When no fresher data is available than 2026-06-18, treat the following as a stale-data example, not a permanent rule:

- 4580: latest visible low and near-term long/short分水岭.
- 4615-4616: latest close/reference area.
- 4660-4665: daily MA5 pressure area from the 2026-06-18 dataset.
- 4660-4675: first反弹承压 observation band.
- 4690-4705: stronger upper resistance from recent highs.

Always recompute these from fresh data before using them in a live plan.

## Output Standards

For a futures operation plan, include:

- Data source and timestamp.
- Whether the quote is live or stale.
- Key levels table.
- Long scenario table.
- Short scenario table.
- Breakdown/reversal scenario if relevant.
- Position-sizing reality: points needed for target profit by 1/2/3 contracts.
- Risk reminder: no guaranteed profit; stop loss first.

Use language like:

- “触发后考虑”
- “若不能站稳/跌破后不能收回，则失效”
- “估计胜率，不是统计承诺”
- “没有触发信号则观望”

Avoid language like:

- “必涨/必跌”
- “保证盈利 5%”
- “现在必须开仓”
- “胜率确定为 X%”

## Common Pitfalls

1. Treating stale public quote data as live. Always check returned `date` and `time`.
2. Inferring active buy/sell from K-lines. K-lines can show price, volume, and open interest, but not exact tick direction.
3. Chasing low-position shorts during RSI extreme oversold. Add confirmation such as failed rebound or broken support retest.
4. Designing a 5% profit target without explaining required points and contract count.
5. Providing only one direction. Futures planning should include both long and short trigger conditions unless user explicitly asks for one side.

## Verification Checklist

- [ ] Data timestamp verified and stale data labeled.
- [ ] 3m/15m/30m/60m/120m/daily data fetched where possible.
- [ ] Open interest and volume changes considered.
- [ ] Tick/active-buy limitations disclosed when unavailable.
- [ ] Each scenario has entry, stop loss, take profit, probability, basis, and invalidation.
- [ ] Markdown reports are saved under `~/.hermes/skills/finance/futures-trading-assistant/reports/` unless user specifies otherwise.
