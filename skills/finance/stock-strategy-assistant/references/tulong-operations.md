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
data/watchlists/          # D3 watch、active watchlist
data/trades/              # 买卖记录，用于派生 HOLD 当前持仓
reports/alerts/           # 盘中 JSONL/CSV/log
reports/reviews/          # 收盘复盘和策略验证结论
src/stock_assistant/      # 可复用规则函数
```

## 架构职责边界

- `references/` 保存当前规则和运行手册，是未来会话应主动加载的事实源。
- `src/stock_assistant/strategy_tulong.py` 保存可复用规则函数。
- `scripts/tulong/selection/` 负责选股、D3 观察池生成和自动窄化入口。
- `scripts/tulong/runtime/` 负责 cron 调用的生产运行脚本。
- `scripts/tulong/` 只负责流程编排、读写数据和被 cron 调度，不应成为长期规则事实源。

D1/D2/D3 规则函数应在 `src/stock_assistant/strategy_tulong.py`，selection 脚本只负责 CLI、数据读取和输出，不应成为唯一规则所有者。

## 文件命名与持仓来源

源文件必须带完整 `YYYYMMDD_HHMMSS` 时间戳：

```text
MMDDD3_D1_filtered_YYYYMMDD_HHMMSS.csv
MMDDD3*_watch*_YYYYMMDD_HHMMSS.csv
```

不要再生成或依赖只有 `HHMMSS` 的旧文件名。watch 源按当日 D 标签下最新 `MMDDD3*_watch*_YYYYMMDD_HHMMSS.csv` 选取，既支持标准 `MMDDD3_watch_scan_...`，也支持带策略标记的 `MMDDD3_new_strategy_full_watch_scan_...`。HOLD 当前持仓不再使用独立源文件，统一从 `data/trades/tulong_trades.csv` 汇总买卖记录派生。

## 买卖截图入账流程

当用户发送当日买卖/持仓明细截图要求“整理到交易文档”时：

1. 交易文档事实源固定为 `data/trades/tulong_trades.csv`，不要写到旧仓库或临时文件。
2. 先识别截图中的 `action`、`code`、`name`、`quantity`、`price`、`amount`、成交时间；再读取 CSV 表头与已有记录，避免重复追加。
3. 视觉模型不可用时，macOS 可用 Vision OCR 兜底：用 Swift `VNRecognizeTextRequest` 读取截图；数字/中文交易截图优先用系统 Vision，比只装英文 tesseract 更可靠。tesseract 可作为补充，但不要把“视觉接口临时 401/语言包下载失败”固化成长期限制。
4. 截图未显示卖出费用时按标准估算并写入 `fee` / `net_amount`，不要留空：买入默认 `5.00 + amount*0.00001`；卖出默认 `5.00 + amount*0.0005 + amount*0.00001`，四舍五入到 2 位。note 标 `费用按标准估算`。
5. `net_amount` 买入为负数 `-(amount+fee)`，卖出为正数 `amount-fee`。
6. `position_ref` 使用原买入所属 D 标签；日内 T 操作要区分 `T操作买入` 与 `T操作卖出旧仓`，卖出旧仓的 `position_ref` 指向旧仓来源。
7. `d3_watch` 以原标的是否属于屠龙 D3 watch 为准；非 D3 监控/策略外标的填 `no`。
8. 写入后必须按 buy/sell 数量汇总核对 open HOLD，确认清仓/剩余持仓与用户截图一致。

## 开盘前流程

固定调度：

```text
15:10-15:30  收盘复盘，生成 D3 表现、HOLD 续期、次日新 D3 观察
08:50        preopen_rotate_watchlist 写入今日 active 池
09:05        preopen_guard_check 校验 active 池
09:25-15:00  watchdog 只使用已校验 active 池
```

`preopen_rotate_watchlist.py` 要做：

- 查找今日最新 `MMDDD3*_watch*_YYYYMMDD_HHMMSS.csv`；
- 读取 `data/trades/tulong_trades.csv`，按代码汇总买入/卖出数量，派生当前 open HOLD；
- 合并写入 `data/watchlists/tulong_active_watchlist.csv`；
- watch 源只切入 `pool_subtype=active` 的行；`radar/backup/exclude` 只保留在源 CSV/报告与 filtered_out 中，不进入正式提醒；
- 保留 `industry`、`trigger_price`、`invalid_price`、`zone_low`、`zone_high`、`rank`、`score`、`pool_subtype`、`note`；
- 过滤 20cm / 非沪深主板；
- 备份旧 active CSV；
- 重置 `last_prices`、`pending_snapshot`，更新 `watchlist_source`、`watch_date`、`stages`、`pool_types`、`filtered_out`；
- 调用 `watchdog.load_watchlist()` 做脚本级验证。

`preopen_guard_check.py` 要读实际 active CSV 和 state，而不是只读观察源文件。成功静默，异常 stdout 投递。

## 盘中提醒

- 行情拉取/事件检测每 1 分钟；
- 提醒每 5 分钟释放一个窗口；当前屠龙 cron 投递到飞书，同轮触发事件不再按“price < trigger”全量推送；分钟级事件仍完整写本地 JSONL/快照。
- 事件分三层：A 级推送（D3 跌破失效/接近失效/进入买点区/从水下回收观察价；HOLD 跌破或接近止损、回收成本）；B 级状态变化才推（D3 有意义的首次跌破观察价、强势不追、冲高回落、快速走弱；HOLD 跌破成本、浮盈减仓/T观察）；C 级只写本地（普通水下、普通观察、重复状态无变化）。
- D3 watch 与 HOLD 使用不同规则：D3 以低吸/回收观察价/失效为主；HOLD 以成本线、止损线、浮盈减仓/T 观察为主。
- 弱事件阈值已收紧：普通 `price < trigger` 只写本地；只有接近买点区的首次水下穿越、涨幅≥7%且高于观察价3%以上的强势、或高点涨幅≥8%且回落≥4%的冲高回落才作为 B 级推送。
- 推送遵循状态变化：同一只股票连续处于同一状态时不重复推送；从观察/水下进入买点区、从水下回收观察价、向失效位靠近或跌破失效时重新推送。
- 同一只股票在 5 分钟窗口内多次触发时，只保留优先级最高的一条；所有分钟级事件仍写本地。
- 15 分钟快照默认只写本地，不推送；
- 多股同轮触发时不合并摘要，按单股告警块输出；
- 若未来切回微信且 iLink 再次限流，再单独恢复微信专用输出压缩/节流，不影响飞书分层输出。

微信告警用 fenced code block 保留换行：

```text
0603D3｜代码 名称｜行业｜水下观察/买点区/回收观察价/接近失效/跌破失效/强势不追
现价 xx（+x.xx%）｜买点 low-high｜止损 invalid
动作：只等回到买点区/回收trigger；跌破invalid放弃
参考：距止损+x.x%｜成交额x.xx亿｜HH:MM
```

## 监控池查询纪律

当用户问“今天监控池有哪些 / 是否正常 / 先忽略 HOLD”时，必须区分 D3 watch 与 HOLD position：

- 只问 D3 且用户明确“先忽略 HOLD”时，先读最新 `MMDDD3_watch_*_YYYYMMDD_HHMMSS.csv` 区分 active/radar，再读 active 中实际已切入的 `stage=MMDDD3,pool_type=watch,pool_subtype=active` 行；
- HOLD 是否进入当前监控池，以 `data/trades/tulong_trades.csv` 汇总后的剩余持仓为准；
- 已经买卖相抵、剩余数量为 0 的代码不进入当前监控池；如 active 混入已清仓 HOLD，要标为污染项并清理；
- 回答“正常”前至少核对 cron 启用且最近 ok、active CSV 是今日 MMDDD3、state 与 active 一致。

## 收盘复盘归因

`runtime/review.py` 输出交易归因时固定分为：D3 active交易、D3 radar观察但未买、HOLD管理、策略外交易、ETF。D3 当日策略表现只看 active 主池内交易；HOLD/T、策略外交易、ETF 不混入当日 D3 胜率。

## 排障顺序

微信没收到提醒时，不要只看 `last_status=ok`：

1. `cronjob(action='list')` 看 watchdog、preopen rotate、guard 的 enabled/state/last_status/last_delivery_error；
2. 查 `reports/alerts/tulong_d3_monitor.log`：`silent minute_check` 表示监控正常但本轮静默，`sent queued_alert` 表示脚本输出过，`fetch_error` 才是行情问题；
3. 查 `~/.hermes/cron/output/<job_id>/...md`，确认是否有 stdout；
4. 只有 gateway/agent 日志出现 `iLink sendmessage rate limited` / `Weixin send failed` 才判断为微信限流。
5. 微信 iLink 仍在 `ret=-2` 限流窗口时，优先把屠龙 cron 临时切到飞书等可用平台，避免继续撞微信窗口。切换前先 `cronjob(action='list')`，更新时保留原 `schedule`、`script`、`no_agent`、`enabled_toolsets`、`workdir` 和中文 `name`，只改 `deliver`；更新后重新 list，确认所有屠龙任务 `deliver=feishu`。

如果用户问“0604D3 监控池有了吗”这类日期+D几问题，先区分“候选/观察池已生成”和“active 监控池已切换”：

1. 查 `data/watchlists/*MMDDD3*watch*.csv`，按 D 标签和完整 `YYYYMMDD_HHMMSS` 时间戳确认最新观察池；注意 `MMDDD3_new_strategy_full_watch_scan_...` 这类带策略标记的文件也可能是当前最新池，不要只查标准 `MMDDD3_watch_scan_...`；
2. 再查 `data/watchlists/tulong_active_watchlist.csv` 的 `stage/pool_type/source_file`，确认 active 是否已经切到当日 MMDDD3，以及 source 是否等于最新时间戳的 watch 文件；
3. 如果 active 仍是前一日，说明池子已生成但尚未通过 08:50 preopen rotate 写入正式监控；不要把候选池说成已经在盘中监控；
4. 如果 active 已切但 source 不是最新 watch 文件，按用户确认可运行 `preopen_rotate_watchlist.py --force` 重新切池，并复查 state/source/validation；
5. 回答时把 D3 watch 与 HOLD position 分开说，HOLD 仍以 `data/trades/tulong_trades.csv` 派生为准。

如果用户指出日期、阶段、HOLD 展示不对，先检查 active CSV 的真实 `stage/pool_type/source_file`，再检查 `scripts/tulong/runtime/watchdog.py` 是否有旧标签硬编码。修复后用 `FORCE_RUN=1` 或脚本函数验证用户可见文本。

## 验证命令

常用验证：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/tulong/runtime/*.py scripts/tulong/selection/*.py
FORCE_RUN=1 ~/.hermes/scripts/tulong_watchdog.sh
```

macOS Vision OCR 临时脚本示例（用于交易截图兜底识别）：

```swift
import Foundation
import Vision
import AppKit

let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: url), let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { exit(1) }
let request = VNRecognizeTextRequest { request, _ in
    let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
    for obs in observations.sorted(by: { abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.015 ? $0.boundingBox.midY > $1.boundingBox.midY : $0.boundingBox.minX < $1.boundingBox.minX }) {
        if let top = obs.topCandidates(1).first { print(top.string) }
    }
}
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
request.recognitionLanguages = ["zh-Hans", "en-US"]
try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
```

修改运行流程、active watchlist 来源、cron 行为、HOLD 派生、日志或排障纪律时，更新本文件；修改脚本入口、目录结构或 wrapper 映射时，更新 `scripts/tulong/README.md`。不要在 README 和本文件重复维护同一套运行事实。