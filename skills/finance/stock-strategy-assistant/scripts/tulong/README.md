# 屠龙脚本目录说明

本目录位于 skill 内：`/Users/fenomenoronaldo/.hermes/skills/finance/stock-strategy-assistant/scripts/tulong/`。

这里只说明脚本目录和入口关系；运行事实、cron 调度、active watchlist、HOLD 派生、日志和排障统一看 `../../references/tulong-operations.md`。D1/D2/D3 策略规则统一看 `../../references/tulong-current-rules.md`。

## 目录索引

```text
selection/ # 选股、D3 观察池生成、自动窄化入口
runtime/   # cron 调用的生产运行脚本
```

## runtime

- `runtime/watchdog.py`：盘中监控脚本，读取 `data/watchlists/tulong_active_watchlist.csv`。
- `runtime/review.py`：收盘复盘脚本。
- `runtime/preopen_rotate_watchlist.py`：开盘前切池脚本，合并今日 D3 watch 与从 `data/trades/tulong_trades.csv` 派生的 HOLD 当前持仓。
- `runtime/preopen_guard_check.py`：开盘前守门校验脚本。

## selection

- `selection/generate_d3_candidates.py`：当前通用 D3 观察池生成器。
  - 参数：`--d1-date`、`--d2-date`、`--d3-date` 或 `--d3-label`、`--timestamp`、`--d1-only`。
  - 输出：`reports/daily/{D3_LABEL}_candidate_scan_{YYYYMMDD_HHMMSS}.md`、`data/watchlists/{D3_LABEL}_watch_scan_{YYYYMMDD_HHMMSS}.csv`。
  - 加 `--d1-only` 时，同时输出 `{D3_LABEL}_D1_filtered_{YYYYMMDD_HHMMSS}.md/.csv`。

示例：

```bash
.venv/bin/python scripts/tulong/selection/generate_d3_candidates.py \
  --d1-date 20260527 \
  --d2-date 20260528 \
  --d3-date 20260529 \
  --timestamp 20260529_214437 \
  --d1-only
```

## Hermes cron wrappers

Cron 的 `script` 字段指向 `~/.hermes/scripts/*.sh`，shell wrapper 再调用本目录脚本：

- `~/.hermes/scripts/tulong_watchdog.sh` -> `scripts/tulong/runtime/watchdog.py`
- `~/.hermes/scripts/tulong_review.sh` -> `scripts/tulong/runtime/review.py`
- `~/.hermes/scripts/preopen_rotate_watchlist.sh` -> `scripts/tulong/runtime/preopen_rotate_watchlist.py`
- `~/.hermes/scripts/preopen_guard_check.sh` -> `scripts/tulong/runtime/preopen_guard_check.py`

## 同步规则

修改脚本入口、目录结构或 wrapper 映射时，更新本 README。修改运行流程、active watchlist 来源、cron 行为、HOLD 派生、日志或排障纪律时，更新 `../../references/tulong-operations.md`。
