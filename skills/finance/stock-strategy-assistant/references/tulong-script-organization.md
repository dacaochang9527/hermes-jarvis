# 屠龙脚本整理与 cron 安全迁移流程

Use this when整理 A 股屠龙/D3/D4 项目里的脚本、cron 包装器、监控脚本目录，尤其是用户说“脚本太乱、哪些在用、能不能放到独立文件夹”。

## Recommended target layout

Project root example:

```text
scripts/tulong/
  README.md
  runtime/      # 生产 cron 正在调用的脚本
  selection/    # 夜间/人工选股、候选池生成脚本
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
cd /Users/fenomenoronaldo/Documents/ai-project/a-share-stock-assistant
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
   - Search for old script-name references in the moved tree and wrappers.
   - If safe, dry-run wrapper scripts; if not safe because they may mutate active watchlists or emit Weixin messages, explicitly report “not dry-run yet”.
   - Check `git status`/diff if the project is a git repo.

## Reporting rule

Do not claim the migration is fully complete just because files moved. Distinguish:

```text
Completed: directory migration, wrapper patching, README, syntax check.
Not yet verified: dry-run / runtime behavior / git diff review.
```

This distinction matters because cron can remain active while wrapper paths are broken, and Weixin delivery failures can hide the final status message.

## Pitfalls from prior session

- A Weixin session may generate the final answer but fail to deliver due to iLink rate limiting. Verify filesystem state directly before answering in CLI.
- Moving scripts can generate new `__pycache__` during `py_compile`; clean only if user wants a tidy tree.
- Do not delete historical scripts during cleanup unless the user explicitly asks; move to `legacy/` first.
