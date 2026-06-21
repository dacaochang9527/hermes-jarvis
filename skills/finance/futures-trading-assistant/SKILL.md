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
- Saving futures analysis to Markdown reports.

Do not use this skill for:

- Guaranteed profit claims.
- Instructions to trade without conditions.
- Analyses that require tick-by-tick order flow when no tick data or screenshot is available.

## Public Data Sources

The current proven public sources for PVC2609 are documented in `references/china-futures-public-data.md`.

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
7. If saving to Markdown, write under `~/.hermes/reports/` unless the user specifies another path.

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
- [ ] Markdown reports are saved under `~/.hermes/reports/` unless user specifies otherwise.
