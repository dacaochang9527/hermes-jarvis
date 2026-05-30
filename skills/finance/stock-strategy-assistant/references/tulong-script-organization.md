# 屠龙脚本整理与 cron 安全迁移流程

> 迁移说明（2026-05-31）：屠龙运行时已从旧项目 `a-share-stock-assistant` 整体迁入本 skill 内，**当前唯一维护位置**：
> `~/.hermes/skills/finance/stock-strategy-assistant/`
> 布局：`scripts/tulong/`（runtime/selection/legacy）、`src/stock_assistant/`（依赖子集）、`data/`、`reports/`、`tests/`、`pyproject.toml`、`.venv/`。
> Hermes cron 的 `~/.hermes/scripts/*.sh` 与 `~/.hermes/cron/jobs.json` 的 workdir 均已指向本 skill 根。旧项目保留为只读归档。

Use this when整理 A 股屠龙/D3/D4 项目里的脚本、cron 包装器、监控脚本目录，尤其是用户说“脚本太乱、哪些在用、能不能放到独立文件夹”。

## Recommended target layout

Project root example:

```text
scripts/tulong/
  README.md
  runtime/      # 生产 cron 正在调用的脚本
  selection/    # 选股、自动窄化、候选池生成脚本
  legacy/       # 历史一次性脚本，仅保留参考
```

Do not leave currently used D3/D4 scripts scattered in `scripts/` root once migration starts.

## Safe workflow

1. Discover active cron jobs first.
   - Record job name, schedule, `script`, `workdir`, mode, last status.
   - Treat `~/.hermes/scripts/*.sh` as the cron entrypoint even when real code lives in the project.

2. Discover project scripts.
   - Identify runtime scripts by cron wrapper references.
   - Identify selection/research scripts separately from production monitor scripts.
   - Keep obviously old one-off scripts under `legacy/`, not deleted.

3. Move files into the target layout.
   - `runtime/`: watchdog, review, preopen rotate, preopen guard.
   - `selection/`: D1 filtering and D3 candidate generation scripts.
   - `legacy/`: old dated scripts.

4. Patch all cron shell wrappers.
   - Example wrapper body after migration:

```bash
cd /Users/fenomenoronaldo/.hermes/skills/finance/stock-strategy-assistant
exec .venv/bin/python scripts/tulong/runtime/watchdog.py "$@"
```

5. Write/update `scripts/tulong/README.md`.
   Include:
   - Which files are production runtime scripts.
   - Which cron job calls each wrapper.
   - Which scripts are selection/research only.
   - Which scripts are legacy.
   - Where outputs/logs are written when known.

6. Verification before saying “complete”.
   - Re-list cron jobs and confirm script names still point to wrappers.
   - Read wrappers and confirm they point to new project paths.
   - Run `python -m py_compile` on moved Python files.
   - For selection generators, keep strategy predicates in `src/stock_assistant/strategy_tulong.py`; scripts under `scripts/tulong/selection/` should be thin orchestration layers. If the user asks to “下沉到 src”, do that refactor immediately, with tests, then update README and skill references.
   - If safe, dry-run wrapper scripts; if not safe because they may mutate active watchlists or emit Weixin messages, explicitly report “not dry-run yet”.
   - Check `git status`/diff if the project is a git repo.

## Reporting rule

Do not claim the migration is fully complete just because files moved. Distinguish:

```text
Completed: directory migration, wrapper patching, README, syntax check.
Not yet verified: dry-run / runtime behavior / git diff review.
```

This distinction matters because cron can remain active while wrapper paths are broken, and Weixin delivery failures can hide the final status message.

## Documentation sync rule

When changing any of the following, update both the project README and the relevant skill reference before reporting completion:

- `scripts/tulong/` directory layout or runtime/selection/legacy responsibilities
- Hermes cron wrapper paths under `~/.hermes/scripts/*.sh`
- Selection CLI parameters, output filenames, or generator responsibilities
- D3/D4 monitoring flow, active watchlist source, or preopen rotation/guard behavior

Default runtime README path（现位于 skill 内）：

```text
~/.hermes/skills/finance/stock-strategy-assistant/scripts/tulong/README.md
```

Default skill references:

```text
stock-strategy-assistant/references/tulong-script-organization.md
stock-strategy-assistant/references/tulong-parameterized-selection.md
stock-strategy-assistant/references/tulong-d3-d4-monitoring.md
```

Keep the split clear: project README documents “how this repo currently runs”; skill references document “how this type of system should be designed next time”.

## Related references

- `references/tulong-parameterized-selection.md`: how to convert dated one-off D3 selection scripts into a reusable `generate_d3_candidates.py` CLI with `--d1-date/--d2-date/--d3-date/--d3-label` and `YYYYMMDD_HHMMSS` timestamped outputs.

## Pitfalls from prior session

- A Weixin session may generate the final answer but fail to deliver due to iLink rate limiting. Verify filesystem state directly before answering in CLI.
- Moving scripts can generate new `__pycache__` during `py_compile`; clean only if user wants a tidy tree.
- Do not delete historical scripts during cleanup unless the user explicitly asks; move to `legacy/` first.
