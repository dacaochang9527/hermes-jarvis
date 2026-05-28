# A 股盘中告警微信格式与复盘日志案例

## 背景

在一次 A 股候选池盘中监控任务中，用户要求“每只股票的每个指标都要换行”。脚本最初已经用普通 `\n` 拼接多行，但微信展示仍被用户反馈“格式还是不对”。后续改为 fenced code block 后，输出在微信里更稳定地保留每个指标独立换行。

## 推荐微信告警格式

用整段代码块包裹，每只股票一个块：

```text
【A股监控】强势拉升
股票：600936 北投科技
现价：6.12
涨跌幅：5.88%
成交额：8.39亿
今开：5.78
最高：6.25
最低：5.69
昨收：5.78
观察价：5.78
失效位：5.26
低吸观察区：5.69–5.80
触发原因：当前涨幅 5.88%，已明显高于观察价，注意不追高
候选买入时机：当前不适合追高；等待回落到观察价附近或尾盘确认后再评估。
行情时间：2026-05-25 11:30:00
口径：候选观察信号，不是确定性交易指令；请结合仓位和风险自行判断。
```

脚本拼接示例：

```python
alert_lines = [
    f"【A股监控】{title}",
    f"股票：{code} {name}",
    f"现价：{price:.2f}",
    f"涨跌幅：{pct:.2f}%",
    f"成交额：{amount_yi}",
    f"今开：{open_price:.2f}",
    f"最高：{high:.2f}",
    f"最低：{low:.2f}",
    f"昨收：{prev_close:.2f}",
    f"观察价：{trigger:.2f}",
    f"失效位：{invalid:.2f}",
    f"低吸观察区：{zone_low:.2f}–{zone_high:.2f}",
    f"触发原因：{reason}",
    f"候选买入时机：{advice}",
    f"行情时间：{quote_time}",
    "口径：候选观察信号，不是确定性交易指令；请结合仓位和风险自行判断。",
]
message = "```text\n" + "\n".join(alert_lines) + "\n```"
```

## 日志管理模式

盘中 watchdog 同时写三类日志：

1. `reports/alerts/<strategy>_events_YYYYMMDD.jsonl`
   - 每条结构化事件一行，字段包含时间、股票、事件类型、价格、涨跌幅、触发原因、候选买入时机、行情时间。
2. `reports/alerts/<strategy>_snapshots_YYYYMMDD.csv`
   - 每轮轮询的行情快照，便于收盘后计算监控内高低点和错过/误报。
3. `reports/alerts/<strategy>_monitor.log`
   - 普通运行日志，记录 fetch_error、sent N alerts、no_alert 等。

收盘复盘脚本读取 JSONL + CSV，生成 Markdown，汇总每只候选的触发事件、监控内高低点、观察价/失效位、低吸观察区和次日处理建议。

## Cron 投递链路演示注意

Hermes cron 中 `schedule="1m"` 可能被解析成“一分钟后一次性运行”，即使设置 `repeat=2` 也要用 `cronjob(action='list')` 核对实际 `repeat`、`next_run_at`、`state`。如果用户只是想验证两次提醒，最稳妥方式是：

- 创建两个明确的一次性任务；或
- 创建一次任务后手动 `cronjob(action='run')` 补发第二次；或
- 用单个脚本内部循环两次并自己控制 sleep（适合短演示，不适合长期 watchdog）。
