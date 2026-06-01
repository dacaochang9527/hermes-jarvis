# 屠龙 D3 生成约定：唯一事实源

> 目的：避免再次出现「D3 观察名单生成到原项目、cron 却读 skill 副本」这类产物落错位置的问题。

## 唯一事实源

- 本 skill 根 `~/.hermes/skills/finance/stock-strategy-assistant` 是屠龙运行时、脚本与数据的**唯一事实源**。
- 历史上的原始开发仓库 `~/Documents/ai-project/a-share-stock-assistant`（git remote: `stock-assistant.git`）已于 **2026-06-01 删除**，以免 Hermes 交互式 agent 把项目根锚定到原项目、把产物写回那边。如需查阅历史，可从 GitHub 远端重新 clone，但**不要**再把它作为运行/生成入口。

## 为什么会跑偏（背景）

- `scripts/tulong/selection/generate_d3_candidates.py` 用 `PROJECT = Path(__file__).resolve().parents[3]` 按**脚本自身位置**推导项目根；因此「跑哪一份脚本，产物就落到那一份项目」的 `data/watchlists/` 与 `reports/daily/`。
- cron 任务已正确收敛到 skill：`~/.hermes/cron/jobs.json` 四个任务的 `workdir`、以及 `~/.hermes/scripts/*.sh` 里的 `cd`，都指向本 skill 根。
- 但**交互式 agent 没有 workdir 约束**，曾就近执行原项目里的脚本副本，导致 `0601D3` 名单落到了原项目。删除原项目后，全机只剩 skill 这一份脚本，交互式生成不会再跑偏。

## 生成 D3 名单的硬性要求

1. 必须在 skill 根执行，不得从任何其他目录的脚本副本生成：

```bash
cd ~/.hermes/skills/finance/stock-strategy-assistant
.venv/bin/python scripts/tulong/selection/generate_d3_candidates.py \
  --d1-date YYYYMMDD --d2-date YYYYMMDD --d3-label MMDDD3 [--d1-only]
```

2. 产物固定落在 skill 内：
   - 观察池：`data/watchlists/{LABEL}_watch_scan_{YYYYMMDD_HHMMSS}.csv`
   - 扫描报告：`reports/daily/{LABEL}_candidate_scan_{YYYYMMDD_HHMMSS}.md`
   - 可选 D1 底池：`data/watchlists/{LABEL}_D1_filtered_*.csv` / `reports/daily/{LABEL}_D1_filtered_*.md`
3. **禁止**新建第二份项目副本或把脚本复制到 skill 之外再运行。
4. 生成只是观察池扫描，要进入盘中监控仍需开盘前切池（`preopen_rotate_watchlist.py` 把 `MMDDD3_watch_*` 合并最新 `HOLD_position_*` 写入 `data/watchlists/tulong_active_watchlist.csv`）。
