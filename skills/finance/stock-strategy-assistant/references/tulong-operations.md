# 屠龙运行手册

本文件只保留当前运行和排障纪律。策略规则见 `references/tulong-current-rules.md`。历史迁移和旧格式笔记已从当前 skill references 中删除，不作为当前事实源。

## 唯一事实源

- 本 skill 根是屠龙脚本、数据、报告的唯一事实源：`/Users/fenomenoronaldo/.hermes/skills/finance/stock-strategy-assistant`。
- 原独立仓库 `/Users/fenomenoronaldo/Documents/ai-project/a-share-stock-assistant` 已删除，不应再作为生成或落盘目标。
- 运行命令统一从 skill 根执行：

```bash
cd /Users/fenomenoronaldo/.hermes/skills/finance/stock-strategy-assistant
.venv/bin/python scripts/tulong/selection/generate_d3_candidates.py --d1-date YYYYMMDD --d2-date YYYYMMDD --d3-label MMDDD3 --d1-only
```

## 目录职责

```text
scripts/tulong/runtime/    # cron 正在调用的运行脚本
scripts/tulong/selection/  # D1/D2/D3 生成和自动窄化入口
data/watchlists/          # D3 watch、HOLD position、active watchlist
reports/alerts/           # 盘中 JSONL/CSV/log
reports/reviews/          # 收盘复盘和策略验证结论
src/stock_assistant/      # 可复用规则函数
```

D1/D2/D3 规则函数应在 `src/stock_assistant/strategy_tulong.py`，selection 脚本只负责 CLI、数据读取和输出，不应成为唯一规则所有者。

## 文件命名

源文件必须带完整 `YYYYMMDD_HHMMSS` 时间戳：

```text
MMDDD3_D1_filtered_YYYYMMDD_HHMMSS.csv
MMDDD3_watch_scan_YYYYMMDD_HHMMSS.csv
MMDDD3_watch_manual_review_YYYYMMDD_HHMMSS.csv
HOLD_position_<reason>_YYYYMMDD_HHMMSS.csv
```

不要再生成或依赖只有 `HHMMSS` 的旧文件名。watch 源按当日 `MMDDD3_watch_*` 最新文件选取；HOLD 源按全局最新 `HOLD_position_*` 选取，并只合并 `position_status=open`。

## 开盘前流程

固定调度：

```text
15:10-15:30  收盘复盘，生成 D3 表现、HOLD 续期、次日新 D3 观察
08:50        preopen_rotate_watchlist 写入今日 active 池
09:05        preopen_guard_check 校验 active 池
09:25-15:00  watchdog 只使用已校验 active 池
```

`preopen_rotate_watchlist.py` 要做：

- 查找今日最新 `MMDDD3_watch_*_YYYYMMDD_HHMMSS.csv`；
- 查找全局最新 `HOLD_position_*_YYYYMMDD_HHMMSS.csv`，只保留 `position_status=open`；
- 合并写入 `data/watchlists/tulong_active_watchlist.csv`；
- 保留 `industry`、`trigger_price`、`invalid_price`、`zone_low`、`zone_high`、`rank`、`score`、`note`；
- 过滤 20cm / 非沪深主板；
- 备份旧 active CSV；
- 重置 `last_prices`、`pending_snapshot`，更新 `watchlist_source`、`watch_date`、`stages`、`pool_types`、`filtered_out`；
- 调用 `watchdog.load_watchlist()` 做脚本级验证。

`preopen_guard_check.py` 要读实际 active CSV 和 state，而不是只读观察源文件。成功静默，异常 stdout 投递。

## 盘中提醒

- 行情拉取/事件检测每 1 分钟；
- 微信提醒每 5 分钟释放一个窗口；
- 同一只股票在窗口内多次触发时，微信只发优先级最高的一条；所有分钟级事件仍写本地；
- 15 分钟快照默认只写本地，不推微信；
- 多股同轮触发时不合并摘要，按单股告警块输出；
- 每次事件检测只要条件满足就允许记录，不做“同一股票 + 同一事件 + 同一天最多一次”的去重。

微信告警用 fenced code block 保留换行：

```text
0603D3｜代码 名称｜行业｜水下观察/买点区/回收观察价/接近失效/跌破失效/强势不追
现价 xx（+x.xx%）｜买点 low-high｜止损 invalid
动作：只等回到买点区/回收trigger；跌破invalid放弃
参考：距止损+x.x%｜成交额x.xx亿｜HH:MM
```

## 监控池查询纪律

当用户问“今天监控池有哪些 / 是否正常 / 先忽略 HOLD”时，必须区分 D3 watch 与 HOLD position：

- 只问 D3 且用户明确“先忽略 HOLD”时，只读最新 `MMDDD3_watch_*_YYYYMMDD_HHMMSS.csv` 与 active 中 `stage=MMDDD3,pool_type=watch` 的行；
- 只有存在当前有效的 `HOLD_position_*` 且 `position_status=open` 时，才把 HOLD 算作当前应监控持仓；
- `position_status=closed` 不进入当前监控池；如 active 混入 closed HOLD，要标为污染项并清理；
- 回答“正常”前至少核对 cron 启用且最近 ok、active CSV 是今日 MMDDD3、state 与 active 一致。

## 排障顺序

微信没收到提醒时，不要只看 `last_status=ok`：

1. `cronjob(action='list')` 看 watchdog、preopen rotate、guard 的 enabled/state/last_status/last_delivery_error；
2. 查 `reports/alerts/tulong_d3_monitor.log`：`silent minute_check` 表示监控正常但本轮静默，`sent queued_alert` 表示脚本输出过，`fetch_error` 才是行情问题；
3. 查 `~/.hermes/cron/output/<job_id>/...md`，确认是否有 stdout；
4. 只有 gateway/agent 日志出现 `iLink sendmessage rate limited` / `Weixin send failed` 才判断为微信限流。

如果用户指出日期、阶段、HOLD 展示不对，先检查 active CSV 的真实 `stage/pool_type/source_file`，再检查 `scripts/tulong/runtime/watchdog.py` 是否有旧标签硬编码。修复后用 `FORCE_RUN=1` 或脚本函数验证用户可见文本。

## 验证命令

常用验证：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/tulong/runtime/*.py scripts/tulong/selection/*.py
FORCE_RUN=1 ~/.hermes/scripts/tulong_watchdog.sh
```

涉及 cron、脚本目录、selection CLI、active watchlist 来源或 D3/HOLD 流程时，必须同步更新 `scripts/tulong/README.md` 和本文件。