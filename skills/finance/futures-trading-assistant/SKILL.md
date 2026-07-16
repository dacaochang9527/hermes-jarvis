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

Mandatory day/night review + forecast handoff rules are documented in `references/session-state-chain.md`.

Trading-session changes for Feishu futures monitors, including day + night cron/script/config alignment, are documented in `references/feishu-trading-session-updates.md`.

Pre-open guard check design is documented in `references/preopen-guard-checks.md`.

Local Markdown report to Feishu online document publishing workflow is documented in `references/feishu-report-publishing.md`. Feishu API limits and workarounds (1000-block cap, chunking failures, pre-conversion trimming) are documented in `references/feishu-publishing-limits.md`.

Reusable futures report structure benchmarks, including time-slice forecast-vs-actual tables, error/logic-adjustment tables, top-down multi-timeframe summaries, and small-account point feasibility, are documented in `references/report-structure-benchmarks.md`.

PVC monitor troubleshooting patterns for cron wrappers, Sina quote fallback, bad-state cleanup, and manual scenario-level promotion are documented in `references/pvc-monitor-troubleshooting.md`.

PVC2609 key-level hierarchy safeguards — including avoiding promotion of far/daily resistance into near-term intraday pressure, deriving next-session levels from the reviewed session's own 15m bars, and blocking automatic publishing when near resistance is too far from session high/close — are documented in `references/pvc-level-sanity-and-session-local-levels.md`.

The current PVC2609 Feishu monitor configuration is `configs/pvc2609_feishu_monitor.yaml`.

Current PVC2609 cron scripts:

- `pvc2609_preopen_guard.py`: no-agent pre-open guard; runs at 08:50 on trading days and prints a Feishu-ready readiness report covering config, cron registration, quote/K-line availability, and local state-file sanity.
- `pvc2609_event_monitor.py`: no-agent event monitor; runs frequently during trading hours and prints only when an event should be pushed. It reads `runtime/pvc2609_feishu_monitor/latest_prediction_levels.json` on each tick so predicted key levels from the latest plan override stale hardcoded levels.
- `pvc2609_half_hour_briefing.py`: no-agent briefing monitor; cron may run every 5 minutes, but the script enforces an approximately 25-30 minute send cooldown during trading sessions. It also reads `latest_prediction_levels.json` so fixed-interval briefing support/resistance follows the latest forecast.
- `pvc2609_generate_session_report.py`（位于本 skill 根目录，不在 `scripts/` 子目录）: local Markdown report generator; fetches Sina quote/K-lines, reads monitor logs, and creates a near-complete 20-section day/night review + next-session plan draft aligned with `reports/pvc2609_20.md`, including multi-timeframe summary, prior-plan validation, time-slice forecast-vs-actual, scenario plans, small-account risk table, and `STATE_HANDOFF`. By default it avoids overwriting existing reports by writing a timestamped draft; `--update-levels` 只用于显式的独立生成流程，定时发布统一由 publisher 在质量门禁通过后更新。
- `pvc2609_preopen_review_publish.py`（位于本 skill 根目录）: despite the legacy filename, cron now runs the three review+forecast reports 10 minutes after the reviewed session closes: 11:40 for上午复盘+午盘预测, 15:10 for日盘复盘+夜盘预测, and 23:10 for夜盘复盘+次日日盘预测. 发布器先生成临时草稿并执行机器质量门禁，通过后才提升正式报告、更新监控关键位和发布飞书；失败返回非零状态并转人工复核。For the 23:10 morning target, the default target date is derived from the latest completed night-session K-line and the next available day-session date, not simply the current natural date.

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
7. For PVC2609 day/night reports, first bootstrap with `python pvc2609_generate_session_report.py --date YYYYMMDD --session day|night`. 正常定时流程由 `pvc2609_preopen_review_publish.py` 执行数据日期、趋势矛盾、关键位层级、方案一致性和止损止盈方向门禁；全部通过即可自动发布，只有失败或异常行情才转人工复核。Add `--overwrite` only when replacing the canonical report, and use `--update-levels` only for an explicitly validated standalone generation.
8. If the generate script **times out**, the cause is almost certainly the Sina API rejecting requests without a Referer header. The script uses bare `urllib.request` which does not set one. Fall back to manual data collection with curl (see "Manual Data Collection Fallback" below).
9. If saving to Markdown, write under `~/.hermes/skills/finance/futures-trading-assistant/reports/` unless the user specifies another path.

### Manual Data Collection Fallback (when the generate script fails)

When the `pvc2609_generate_session_report.py` times out due to Sina API Referer requirements, collect data manually:

**Quote snapshot:**
```bash
curl -s --max-time 10 -H "Referer: https://finance.sina.com.cn" "https://hq.sinajs.cn/list=nf_V2609"
```

**Daily K-line (last 5 entries):**
```bash
curl -s --max-time 15 -H "Referer: https://finance.sina.com.cn" \
  "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_D=/InnerFuturesNewService.getDailyKLine?symbol=V2609"
```

**3m/15m K-lines (replace type=15 with 3/15/30/60/120):**
```bash
curl -s --max-time 15 -H "Referer: https://finance.sina.com.cn" \
  "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_3=/InnerFuturesNewService.getFewMinLine?symbol=V2609&type=3"
```

**JSONP cleanup and parsing:** The Sina API wraps JSON in JSONP with optional redirect script. Use Python:
```python
import re, json
raw = curl_output  # as saved from curl
# Strip redirect script if present:
clean = re.sub(r'^/\*<script>.*?</script>\*/', '', raw)
# Extract JSON array:
m = re.search(r'=\s*\((\[.*\])\s*\);', clean, re.DOTALL)
js = m.group(1)
# Remove control characters (Sina sometimes embeds literal \n in strings):
js_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', js)
data = json.loads(js_clean)
today = [b for b in data if b.get('d','').startswith('YYYY-MM-DD')]
```

**Parsing quote data (Sina futures format for PVC2609):**
```
- Field order: name,time_code(150418=15:04:18),open,prev_settlement,current,high,low,...,date
- Daily K-line fields: d(date), o(open), h(high), l(low), c(close), v(volume), p(open_interest)
```

**Monitor logs:**
```bash
# Half-hour briefings for today:
grep "YYYY-MM-DD" runtime/pvc2609_feishu_monitor/half_hour_briefings.jsonl

# Events for today (file can be large, tail + filter):
tail -200 runtime/pvc2609_feishu_monitor/events.jsonl | grep "YYYY-MM-DDTHH:"
```

A reusable script `scripts/fetch_sina_pvc2609.py` is available that handles the Referer header, JSONP parsing with control-character cleanup, and both quote + K-line fetching. Use it instead of hand-writing curl commands each time:
```bash
python scripts/fetch_sina_pvc2609.py --quote
python scripts/fetch_sina_pvc2609.py --kline daily --last 5
python scripts/fetch_sina_pvc2609.py --kline 3 --filter-today
python scripts/fetch_sina_pvc2609.py --kline 15 --filter-today
```

After collecting data, write the report directly following the 20-section structure. Save to `reports/` and proceed to Feishu publishing.

### PVC2609 复盘落盘纪律（用户纠正后固化）

当用户要求“日盘/夜盘复盘、先落盘本地、生成报告、发布飞书、发群”等 PVC2609 复盘类任务时，不要直接手写 canonical Markdown。必须先运行固化脚本生成接近完整成稿的 20 节草稿；正式定时发布走 publisher 的机器质量门禁，门禁通过后自动闭环，失败时才人工复核：

```bash
python pvc2609_generate_session_report.py --date YYYYMMDD --session day|night
```

- 质量门槛：生成草稿应尽量接近 `reports/pvc2609_20.md` 的完整成稿形态，目标约 20 个二级章节，覆盖一句话结论、总评、行情摘要、四段分时复盘、多周期表、前序方案逐项验证、时间维度验证、命中/偏差归因、本地监控、关键位变化、次时段影响、关键点位、情景概率、A/B/C/D 方案、优先级、小资金点数现实、执行纪律、最终口径和 `STATE_HANDOFF`。若脚本输出只有骨架、大片“待补充/需人工补充”，应优先修脚本，而不是接受骨架作为流程完成。
- 若 canonical 文件已存在且不确定是否可覆盖，先用 `--output reports/<name>.script_draft.md` 生成脚本草稿，不要直接 `--overwrite`.
- 正式文件顶部应注明生成方式：由 `pvc2609_generate_session_report.py` 自动生成接近完整成稿的 20 节草稿，发布前经机器质量门禁验证；门禁异常时再人工修正前序验证、分时复盘、关键位与下一交易时段方案。
- 人工复核只处理门禁失败或数据异常；复核时以脚本完整草稿为基底，校正前序计划逐项验证、时间维度预测 vs 实际、监控日志样本、关键位变化、`STATE_HANDOFF`，而不是另起一份纯手工文档，也不要退回大片“待补充/自动骨架”占位。
- 监控日志样本必须二次核对真实 `runtime/pvc2609_feishu_monitor/events.jsonl` 与 `half_hour_briefings.jsonl`。如果生成器把样本写成 0、暂无或与日志明显不一致，应先人工补入第 3/8 节，再发布飞书文档；不能把缺失监控验证的报告当成完成。
- 生成器已知 bug 防范清单（每次复盘复核时逐项检查）：
  1. **Section 3 监控样本数**：生成器经常写 `0 条`，应从 `events.jsonl` / `half_hour_briefings.jsonl` 提取真实计数。events.jsonl 非常大，用 tail 取尾段按日期过滤；half_hour_briefings.jsonl 较小，逐条过滤当日。
  2. **Section 5 前序验证表**：生成器倾向给所有方案填一样的占位文本（如"部分触发但延续失败"），应改为每个方案独立交叉验证 —— 写清楚是否触发、触发时价格、是否确认、是否失败。状态词用：触发且确认、午后触发、未触发、部分触发、触发后失败。
  3. **Section 8 监控样本表**：当生成器输出"暂无/无本地样本"时，用 half_hour_briefings 的 price+levels 按时间排列表格，再取 events.jsonl 中 A 级 event（event_key/support_break/prediction_level_break 等）插入表格，标注 trigger_reason 和 oi_delta。
  4. **STATE_HANDOFF**：检查 must_watch_levels 是否有重复 price 条目（如 4460 出现两次不同 role），检查前序计划来源 doc 是否正确。
  5. **一句话结论**：确认不含占位符/错写（如 "4460/4460"），确认包含今日实际高低点和核心叙事。
- 如果因流程偏差先手写了报告，应立即补跑脚本生成 draft，并把正式文件改造成“脚本完整草稿 + 人工复核修正”版本，保留 draft 作为追溯依据。

## Mandatory Day/Night State Chain

For PVC2609 day/night work, new reports must use a two-document rolling chain unless the user explicitly requests separate files:

- Day close: `reports/{contract}_{YYYYMMDD}_day_review_night_plan.md`, combining the completed日盘复盘 and the same natural day's夜盘预测/操作计划.
- Night close: `reports/{contract}_{YYYYMMDD}_night_review_next_day_plan.md`, combining the completed夜盘复盘 and the次日日盘预测/操作计划.

Every review must compare each prior plan/scenario against actual movement in a Markdown table, including scenarios that did not trigger, with columns for planned trigger, actual path, match status, reason, and execution implication.

After finalizing any forecast/operation plan, update `runtime/pvc2609_feishu_monitor/latest_prediction_levels.json` so automatic event and half-hour monitors use the latest predicted key levels instead of stale hardcoded levels. See `references/session-state-chain.md` for schema and handoff block format.

## Local Report ↔ Feishu Document Workflow

When the user asks to save a futures report and make it available in Feishu, treat the workflow as a three-step closed loop:

1. First save the canonical Markdown report under `~/.hermes/skills/finance/futures-trading-assistant/reports/` with a stable filename such as `{contract}_{YYYYMMDD}_{session_or_purpose}.md`.
2. Create the Feishu online document from that local Markdown using the fixed publisher script `publish_feishu_markdown_doc.py` documented in `references/feishu-report-publishing.md`. The script uses the official Feishu Markdown-to-docx block converter plus descendant insertion; do not hand-build Markdown blocks or reimplement the OpenAPI flow ad hoc.
3. After the Feishu document is created and its final URL is known, immediately patch the local Markdown metadata block near the top with a line like `> 飞书在线文档：https://...`.
4. If the Feishu document is later copied/recreated/retitled and the URL changes, patch the local Markdown link to the final retained URL and delete or ignore superseded URLs.
5. Only then send the final Feishu document link to the group when the user asks for group delivery.

This keeps the local report as the durable source of truth while preserving a direct pointer to the online Feishu version.

### Personal Trade Record Review Before Publishing

When the user asks for a day/night session review plus “落盘、飞书文档、发群”, first check whether user-side成交/持仓/资金 data is expected. If the user says they will provide today’s trading data, pause generation and wait; do not publish a review based only on market data and monitor logs.

If the user provides成交截图:

- Extract visible fields: contract, direction, fill price, volume, fill time, and preserve that the screenshot may be partial.
- Combine personal fills with the pre-session plan and actual K-line path to review execution quality, not just market direction.
- If the screenshot lacks complete流水、手续费、平仓盈亏、持仓汇总, do not calculate exact P&L. Say explicitly that the review covers direction, rhythm, target/stop discipline, and visible execution structure only.
- Distinguish “plan matched the market” from “execution quality”: e.g. key-level confirmation, fragmented small orders, target-zone profit taking, second-entry conditions after first target is reached.
- In the Feishu group message, summarize only the conclusion and document link; do not paste the full trade table or sensitive account details.

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
- Opening response table: high-open / flat-open / low-open / extreme gap handling with key observation levels. This is a conditional opening plan, not a promise to predict the exact open.
- Long scenario table.
- Short scenario table.
- Breakdown/reversal scenario if relevant.
- Unified operation summary table before detailed A/B/C/D scenarios, with direction, entry condition, key levels, stop/invalidation, take-profit, and risk note.
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
6. Sending >1000 blocks to the Feishu descendant API. The endpoint rejects large payloads; pre-trim the markdown (remove STATE_HANDOFF + optional sections like 小资金点数) before conversion to stay under the limit. The `publish_feishu_markdown_doc.py` script now uses single-shot with a 950-block guard — multi-call chunking does NOT work (error 1770041 "open schema mismatch") and was removed. If publishing fails, trim more aggressively and retry. See `references/feishu-publishing-limits.md`.
7. Publishing a review report where the monitor loaded stale prediction levels from a prior plan. The monitor reads `latest_prediction_levels.json` at startup; if a new plan was generated but not deployed before the monitor started, alerts fire against old levels. Run `--update-levels` on the reviewed plan before the next session's monitor starts. If the gap cannot be closed, note the discrepancy in the review's Section 7.
8. **Sina API blocks bare urllib requests.** The generate script (`pvc2609_generate_session_report.py`) uses `urllib.request` without a `Referer` header and will hang/time out. Sina requires `Referer: https://finance.sina.com.cn`. When the script fails, fall back to manual data collection with curl (see "Manual Data Collection Fallback" above). Consider fixing the script by adding the Referer header.
9. **关键位层级错位会误导盘中计划。** 生成下一时段午盘/夜盘预测时，近端压力/支撑必须从“被复盘时段”的 15m K线推导，不能用全量历史15m直接取分位数，否则会把日K级别远端强反抽位（如 4475-4495）误写成近端压力。远端位可保留为“大级别修复门槛/远端观察”，但不能作为当前时段第一做空参考。自动发布前应做 sanity check：近端压力若距离复盘高点与收盘均超过约50点，阻止发布并要求人工复核。详见 `references/pvc-level-sanity-and-session-local-levels.md`.

## Verification Checklist

- [ ] Data timestamp verified and stale data labeled.
- [ ] 3m/15m/30m/60m/120m/daily data fetched where possible.
- [ ] Open interest and volume changes considered.
- [ ] Tick/active-buy limitations disclosed when unavailable.
- [ ] Each scenario has entry, stop loss, take profit, probability, basis, and invalidation.
- [ ] 正式发布已通过机器质量门禁；门禁失败时未写入新监控关键位、未调用飞书发布，并返回非零状态。
- [ ] Next-session plan includes an opening response table covering high-open, flat-open, low-open, and extreme-gap handling.
- [ ] Next-session plan includes one unified operation summary table combining A/B/C/D/E plans for quick group review.
- [ ] Markdown reports are saved under `~/.hermes/skills/finance/futures-trading-assistant/reports/` unless user specifies otherwise.
- [ ] Generate script timed out? Fall back to manual data collection with `curl -H "Referer: https://finance.sina.com.cn"`.
- [ ] Feishu publish failed? Check if `total_blocks > 950` (trim STATE_HANDOFF, 小资金, detailed schemes) or check for error 1770041 (chunking was removed — single-shot only).
