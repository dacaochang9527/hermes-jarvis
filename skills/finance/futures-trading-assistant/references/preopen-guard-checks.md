# Futures Pre-open Guard Checks

Use this reference when adding or maintaining pre-open readiness checks for futures Feishu monitors.

## Purpose

A pre-open guard check verifies that the monitoring system can work before the trading session starts. It is not a trading signal and should not produce directional advice.

For PVC2609, the day-session guard runs at 08:50 on trading days before the 09:00 event monitor and half-hour briefing start. The night-session guard runs at 20:50 on trading days before the 21:00 night event monitor and half-hour briefing start.

## Recommended Checks

- Cron registration: event monitor and briefing jobs exist, are enabled, and have the expected schedule/delivery target.
- Feishu template/config: target group exists in config and group-push templates include `@所有人` unless the user requested a quiet push.
- Quote snapshot: public quote endpoint returns parseable fields, including last price and quote timestamp.
- K-lines: 3m and 15m K-line endpoints return enough parseable rows for the monitor to derive levels and structure.
- Data freshness labeling: pre-open quote data may be from the prior trading day; label it as a pre-open/possibly stale snapshot instead of treating it as live.
- Local state sanity: cooldown/dedupe JSON files are readable or absent; malformed state should be reported before the session starts.

## Output Pattern

Keep the message operational and concise:

```text
PVC2609｜08:50｜开盘前守门校验
状态：通过；09:00后进入事件监控，半小时简报同步待命
✓ 配置：配置OK：群目标、交易时段、@所有人模板均存在
✓ Cron：Cron OK：事件监控与半小时简报任务存在
✓ 行情：行情OK：现价 4616，quote 06-18 15:03:24，3m 1023条，15m 1023条，盘前可能为上一交易日快照
✓ 状态文件：状态OK：cooldown/dedupe文件可读或尚未生成
提醒：盘前不做交易判断；09:00后若行情延迟超过180秒，将标记疑似延迟并避免强操作结论。
```

## Pitfalls

- Do not send operation advice from the guard check.
- Do not require the pre-open quote to be live; require only that it is parseable and clearly labeled.
- Do not silently suppress guard failures. A failed guard should still print a Feishu-ready status message with the failing checks.
- Do not assume a YAML message template is used by runtime scripts; inspect whether scripts hardcode output before relying on config-only changes.
