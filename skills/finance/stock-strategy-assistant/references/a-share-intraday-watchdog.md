# A 股盘中告警 Watchdog 模式

## 适用场景

用户已经有少量观察股/观察池，希望 Hermes 在盘中自动监控并只在触发时通知，而不是每次都由 LLM 轮询分析。

## 已验证模式

- 用 `cronjob(no_agent=True)` 创建脚本型定时任务。
- 脚本放在 `~/.hermes/scripts/`，cron 创建时 `script` 只填相对文件名，例如 `tulong_watchdog.sh`。
- 脚本 stdout 非空才投递；stdout 为空则静默，适合低噪音告警。
- 监控脚本维护状态文件，主要记录上一轮价格和待处理快照；当前不做“每票每事件每天一次”的告警去重，事件条件每次重新满足时都允许再次输出。
- 定时任务建议投递到 `origin`，这样从微信发起的任务会回到当前微信会话。

## 少量 A 股实时行情数据源

当只监控少量股票时，新浪行情接口比全市场 AkShare spot 更轻：

```python
import re, requests

symbols = "sh600936,sh600578,sz003007,sh603373"
resp = requests.get(
    f"https://hq.sinajs.cn/list={symbols}",
    timeout=10,
    headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
)
text = resp.content.decode("gbk", errors="ignore")
for symbol, payload in re.findall(r'var hq_str_(s[hz]\\d{6})="(.*?)";', text):
    parts = payload.split(",")
    # 字段：名称, 今开, 昨收, 现价, 最高, 最低, ..., 成交量, 成交额, 日期, 时间
```

市场前缀：`6xxxxx -> sh`，其他常见 A 股代码多为 `sz`。

## 告警口径建议

低噪音默认规则：

- 跌破失效位：风险/策略失效提醒；
- 接近失效位：风控提醒；
- 低于观察价：D3 水下观察提醒；
- 从观察价下方回收：承接/回收提醒；
- 大幅拉升：提醒“不追高”；
- 快速走弱：风险提醒；
- 盘中冲高回落：异动提醒；
- 每次事件检测只要条件满足就允许提醒；不做“同一股票 + 同一事件 + 同一天最多一次”的去重。

## 买入时机提示与复盘日志

当用户要求“建议买入时机”时，仍保持合规边界：输出观察条件，而不是确定性买入指令。

推荐表达：

- `低吸观察区`：用观察价和失效位计算一个价格区间，例如 `max(失效位*1.015, 观察价*0.985)` 到 `观察价*1.003`。
- `观察买入时机`：仅在低吸观察区内观察低吸/小仓试错；跌破失效位策略失效，不补仓；快速拉离观察价不追。
- `回收观察价`：从水下回到观察价上方后，先看能否站稳；若回落不破观察价且量价温和，作为确认型观察点。
- `强势拉升/冲高回落`：提示不追高，等待回落到观察价附近或尾盘确认后再评估。
- `接近/跌破失效位`：暂不考虑观察买入，优先风险释放，跌破则移出观察池。

日志管理应至少写三类文件，便于收盘复盘：

1. 结构化事件日志：`reports/alerts/<strategy>_events_YYYYMMDD.jsonl`，每条记录 event、code、price、pct、trigger_price、invalid_price、entry_zone、reason、advice、quote_time。
2. 行情快照：`reports/alerts/<strategy>_snapshots_YYYYMMDD.csv`，每轮每只票记录价格、涨跌幅、开高低、昨收、成交额、观察价、失效位。
3. 普通运行日志：`reports/alerts/<strategy>_monitor.log`，记录 fetch_error、sent N alerts、no_alert 等运行状态。

收盘后可用独立脚本生成 `reports/reviews/<strategy>_review_YYYYMMDD.md`，并用 cron 在 15:10 投递。复盘报告应汇总：监控样本数、事件数、每只票触发事件、监控内高低点、当前价/收盘附近价、次日继续观察/移除/等待回踩的结论。

## 微信/iLink 防限流模式

当用户反馈“脚本仍在跑，但微信侧收不到消息”时，必须同时查两类证据：

1. 监控脚本本地日志/cron output：确认是否仍有 stdout，例如 `~/.hermes/cron/output/<job_id>/...md`、`reports/alerts/*_monitor.log`；
2. Hermes 网关/cron 投递日志：搜索 `rate limited`、`iLink sendmessage rate limited`、`delivery error`、对应 `job_id`。

如果本地日志显示 `sent monitor_report` / `sent alert(s)`，但 gateway/agent 日志出现：

```text
[Weixin] rate limited ...
iLink sendmessage rate limited: ret=-2
cron.scheduler: delivery error: Weixin send failed
```

结论应明确写成：**监控没有停，微信 iLink 投递被限流**，不要误报为脚本故障或行情异常。

防限流默认改法：

- 只把“新单股事件”输出到 stdout；
- 15 分钟全量快照只写本地 CSV/JSONL/日志，不再推送微信；
- 事件与快照撞车时，不再排队补发快照；旧 `pending_snapshot` 应清空或在下一轮丢弃；
- 同一轮/同一分钟多只股票触发时，不合并成一条摘要；仍按单股告警块分别输出，便于微信端逐条阅读和处理；
- 状态文件只保留上一轮价格、待处理快照等运行状态；不再用 `sent` 做同日同事件去重；
- cron output 仍会保存每次非空 stdout，可作为微信未收到时的补查凭据。

这种模式牺牲“定时全量播报”，保留“真正有新事件时提醒”，适合 Weixin/iLink 易限流通道。

## 验证步骤

1. 先 `FORCE_RUN=1 ~/.hermes/scripts/<script>.sh` 试跑，确认能取行情。
2. 再不带 `FORCE_RUN` 试跑，确认非交易时间静默退出。
3. 创建 cron 后立刻 `cronjob(action='run')` 或 `hermes cron run <id>` 触发一次。
4. 用 `cronjob(action='list')` 确认任务启用、下次运行时间和投递目标。
5. 若需要向用户演示“轮询提醒 N 次”，不要只依赖 `schedule="1m"` + `repeat=N` 的直觉语义；创建后必须检查列表里的 `repeat`、`next_run_at`、`last_status`。如果只跑了 1 次或 `next_run_at` 为空，立即用 `cronjob(action='run')` 补发或改成 N 个明确的一次性任务。

## 注意边界

这类系统只应输出“观察、触发、风险、失效”语言，不输出确定性买卖建议。盘中提醒优先限制在自选/观察池，不做全市场噪音扫描。
