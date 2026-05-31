# 屠龙脚本目录说明

> 位置：本目录现位于 hermes skill 内（`~/.hermes/skills/finance/stock-strategy-assistant/scripts/tulong/`），是屠龙运行时的唯一维护位置；下文所有相对路径（`scripts/`、`src/`、`data/`、`reports/`）均相对该 skill 根。

本目录集中管理 A 股屠龙 D3 选股与持仓监控相关脚本，避免散落在 `scripts/` 根目录。

## 总体关系：skill / src / scripts

```text
skill reference        = 规则说明书 / 判断标准
src/stock_assistant    = 可复用规则执行器
scripts/tulong         = 流程编排器 / 实际运行脚本
```

- skill 负责长期口径：D1/D2/D3 定义、D3观察区分层、HOLD 持仓事实、提醒降噪、文件命名、切池和验证纪律。
- `src/stock_assistant/strategy_tulong.py` 负责把规则沉淀成可复用函数，后续应逐步减少 selection/runtime 脚本里的重复硬编码。
- `scripts/tulong/` 负责读数据、调规则、写 CSV/Markdown、被 cron 调度和运行。

文档同步约定：以后如果修改 `scripts/tulong` 目录结构、runtime/selection/legacy 分工、cron wrapper、候选池生成器参数或 D3 选股/HOLD 持仓流程，必须同步更新本 README，并视情况同步 `stock-strategy-assistant` skill 的相关 reference。

## runtime/：生产调度正在使用

这些脚本由 Hermes cron 通过 `~/.hermes/scripts/*.sh` 包装调用。

- `runtime/watchdog.py`
  - 盘中监控脚本。
  - 读取 `data/watchlists/tulong_active_watchlist.csv`。
  - 写入 `reports/alerts/tulong_d3_monitor.log`、`tulong_d3_events_YYYYMMDD.jsonl`、`tulong_d3_snapshots_YYYYMMDD.csv`。

- `runtime/review.py`
  - 收盘复盘脚本。
  - 当前由 cron `A股屠龙D3四股收盘复盘` 在 15:10 调用。

- `runtime/preopen_rotate_watchlist.py`
  - 开盘前切池脚本。
  - 08:50 cron 调用，合并今日 `MMDDD3_watch_*` 观察源与最新 `HOLD_position_*` 持仓源到 active 池。
  - HOLD 只接收 position 源文件；若混入 HOLD/watch 行会被拒绝。

- `runtime/preopen_guard_check.py`
  - 开盘前守门校验脚本。
  - 09:05 cron 调用，校验 active 池日期、stage、pool_type、20cm过滤、脚本读取一致性。

## selection/：选股/候选池生成脚本

这些是研究、自动窄化和生成候选池用的脚本，不直接被 cron 盘中调用。

- `selection/generate_d3_candidates.py`
  - 当前唯一保留的通用 D3 候选池生成器。
  - D1 过滤规则已下沉到 `src/stock_assistant/strategy_tulong.py`：`is_main_board_10cm()`、`is_excluded_name()`、`is_first_board_from_zt_row()`、`evaluate_d1_board()`。
  - 本脚本只负责数据源读取、调用 D1/D2 规则执行器、自动窄化、写 CSV/Markdown；不再保存 `EXCLUDE_PREFIXES`、`EXCLUDE_NAME_PARTS` 或 D1 首板判定副本。
  - 参数化接收 `--d1-date`、`--d2-date`、`--d3-date` 或 `--d3-label`、`--timestamp`。
  - 输出 `reports/daily/{D3_LABEL}_candidate_scan_{YYYYMMDD_HHMMSS}.md` 和 `data/watchlists/{D3_LABEL}_watch_scan_{YYYYMMDD_HHMMSS}.csv`。
  - 加 `--d1-only` 时，同时输出 `{D3_LABEL}_D1_filtered_{YYYYMMDD_HHMMSS}.md/.csv`。
  - 0529D3 的旧一次性脚本已删除：`list_0529d3_d1_filtered.py`、`select_0529d3_candidates.py`。
  - 示例：

```bash
.venv/bin/python scripts/tulong/selection/generate_d3_candidates.py \
  --d1-date 20260527 \
  --d2-date 20260528 \
  --d3-date 20260529 \
  --timestamp 20260529_214437 \
  --d1-only
```

## legacy/：历史一次性脚本

- `legacy/select_tulong_d3_layered_20260526.py`
  - 0526 旧版分层筛选脚本，仅作历史参考，不再作为当前主流程。

## Hermes cron 包装脚本

Cron 的 `script` 字段仍指向 `~/.hermes/scripts/*.sh`，这些 shell 包装器已更新为调用本目录：

- `~/.hermes/scripts/tulong_watchdog.sh` -> `scripts/tulong/runtime/watchdog.py`
- `~/.hermes/scripts/tulong_review.sh` -> `scripts/tulong/runtime/review.py`
- `~/.hermes/scripts/preopen_rotate_watchlist.sh` -> `scripts/tulong/runtime/preopen_rotate_watchlist.py`
- `~/.hermes/scripts/preopen_guard_check.sh` -> `scripts/tulong/runtime/preopen_guard_check.py`
