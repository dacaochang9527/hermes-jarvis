# A 股盘中告警 Watchdog 模式

## 适用场景

用户已经有少量候选股/观察池，希望 Hermes 在盘中自动监控并只在触发时通知，而不是每次都由 LLM 轮询分析。

## 已验证模式

- 用 `cronjob(no_agent=True)` 创建脚本型定时任务。
- 脚本放在 `~/.hermes/scripts/`，cron 创建时 `script` 只填相对文件名，例如 `tulong_watchdog.sh`。
- 脚本 stdout 非空才投递；stdout 为空则静默，适合低噪音告警。
- 监控脚本自己维护状态文件，做“每票每事件每天最多提醒一次”等去重。
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
- 每只票每类事件每天最多提醒一次。

## 买入时机提示与复盘日志

当用户要求“建议买入时机”时，仍保持合规边界：输出候选观察条件，而不是确定性买入指令。

推荐表达：

- `低吸观察区`：用观察价和失效位计算一个价格区间，例如 `max(失效位*1.015, 观察价*0.985)` 到 `观察价*1.003`。
- `候选买入时机`：仅在低吸观察区内观察低吸/小仓试错；跌破失效位策略失效，不补仓；快速拉离观察价不追。
- `回收观察价`：从水下回到观察价上方后，先看能否站稳；若回落不破观察价且量价温和，作为确认型观察点。
- `强势拉升/冲高回落`：提示不追高，等待回落到观察价附近或尾盘确认后再评估。
- `接近/跌破失效位`：暂不考虑候选买入，优先风险释放，跌破则移出观察池。

日志管理应至少写三类文件，便于收盘复盘：

1. 结构化事件日志：`reports/alerts/<strategy>_events_YYYYMMDD.jsonl`，每条记录 event、code、price、pct、trigger_price、invalid_price、entry_zone、reason、advice、quote_time。
2. 行情快照：`reports/alerts/<strategy>_snapshots_YYYYMMDD.csv`，每轮每只票记录价格、涨跌幅、开高低、昨收、成交额、观察价、失效位。
3. 普通运行日志：`reports/alerts/<strategy>_monitor.log`，记录 fetch_error、sent N alerts、no_alert 等运行状态。

收盘后可用独立脚本生成 `reports/reviews/<strategy>_review_YYYYMMDD.md`，并用 cron 在 15:10 投递。复盘报告应汇总：监控样本数、事件数、每只票触发事件、监控内高低点、当前价/收盘附近价、次日继续观察/移除/等待回踩的结论。

## 验证步骤

1. 先 `FORCE_RUN=1 ~/.hermes/scripts/<script>.sh` 试跑，确认能取行情。
2. 再不带 `FORCE_RUN` 试跑，确认非交易时间静默退出。
3. 创建 cron 后立刻 `cronjob(action='run')` 或 `hermes cron run <id>` 触发一次。
4. 用 `cronjob(action='list')` 确认任务启用、下次运行时间和投递目标。
5. 若需要向用户演示“轮询提醒 N 次”，不要只依赖 `schedule="1m"` + `repeat=N` 的直觉语义；创建后必须检查列表里的 `repeat`、`next_run_at`、`last_status`。如果只跑了 1 次或 `next_run_at` 为空，立即用 `cronjob(action='run')` 补发或改成 N 个明确的一次性任务。

## 注意边界

这类系统只应输出“候选观察、触发、风险、失效”语言，不输出确定性买卖建议。盘中提醒优先限制在自选/候选池，不做全市场噪音扫描。
