# Cursor AppleScript 技能与自动化插件迁移总结

## 提交概览

- 提交：`ea025fd52`
- 标题：`feat(cursor-automation): 新增 Cursor AppleScript 技能与自动化插件`
- 时间：`2026-06-28T00:46:22+08:00`

这次提交的主线是为 Hermes 增加一套 macOS 上驱动 Cursor IDE 的 AppleScript 技能，以及一个面向 gateway / 飞书的 Cursor 自动化插件。它处理的是 Cursor 这个 Electron IDE，不是 Codex CLI。

## 核心新增

### Cursor AppleScript 技能

目录：`skills/apple/cursor-applescript/`

这个 skill 负责用 AppleScript 和键盘模拟控制 Cursor：

- 列出 Cursor 当前打开的工作区窗口。
- 按工作区名聚焦目标 Cursor 窗口。
- 通过 Cursor 的模型选择器切换模型。
- 切模型后向 Composer 提交任务。
- 切模型后向 Cursor Chat 提问。
- 提供读取 Cursor 本地历史 SQLite 数据库的参考文档。

关键文件：

- `skills/apple/cursor-applescript/SKILL.md`
- `skills/apple/cursor-applescript/references/cursor-history.md`
- `skills/apple/cursor-applescript/scripts/list_cursor_windows.sh`
- `skills/apple/cursor-applescript/scripts/switch_cursor_model.sh`
- `skills/apple/cursor-applescript/scripts/submit_cursor_composer.sh`
- `skills/apple/cursor-applescript/scripts/ask_cursor_chat.sh`
- `skills/apple/cursor-applescript/scripts/dispatch_cursor_model.sh`
- `skills/apple/cursor-applescript/scripts/dispatch_cursor_run.sh`
- `skills/apple/cursor-applescript/scripts/dispatch_cursor_ask.sh`
- `skills/apple/cursor-applescript/scripts/focus_cursor_window.scpt`
- `skills/apple/cursor-applescript/scripts/switch_cursor_model.scpt`

### Cursor 自动化插件

目录：`plugins/cursor-automation/`

这个插件让 Hermes gateway 可以不经过 LLM，直接把命令或自然语言路由到 Cursor AppleScript 脚本。

能力包括：

- 注册 `/cursor-model`：切换 Cursor 模型；如果带 prompt，则切模型后提交 Composer。
- 注册 `/cursor-run`：切模型并向 Composer 提交任务。
- 注册 `/cursor-ask`：切模型并向 Cursor Chat 提问。
- 在 `pre_gateway_dispatch` 阶段识别自然语言 Cursor 控制意图，并改写成 slash command。
- 在 `pre_llm_call` 阶段注入最近一次 Cursor 自动化记录，方便后续追问。
- 将 prompt 通过 `CURSOR_AUTOMATION_PROMPT` 环境变量传递，减少 shell quoting 导致的中文或长文本截断风险。

关键文件：

- `plugins/cursor-automation/plugin.yaml`
- `plugins/cursor-automation/__init__.py`
- `plugins/cursor-automation/nl_parser.py`
- `plugins/cursor-automation/session_context.py`

### macos-computer-use 文档扩展

文件：`skills/apple/macos-computer-use/SKILL.md`

这次提交补充了 AppleScript fallback 文档，说明当 `computer_use` 不可用时，可以通过 `osascript` 驱动 macOS 应用。文档中特别强调了 Cursor 场景：

- 用户说 Cursor 时，指 Cursor IDE，不要路由到 Codex CLI。
- 长中文或 Unicode 文本要用 `pbcopy + Cmd+V`，不要直接 `keystroke`。
- Cursor 模型切换应加载 `cursor-applescript` skill。
- 指定窗口时要传 `--window` 或 `--workspace`，值使用工作区文件夹名，不要用 Tab 标题。

## 使用方式

### Slash command

```bash
/cursor-model gpt-5.5
/cursor-model --window startell gpt
/cursor-model --window .hermes gpt-5.5 Write upgrade plan to .hermes/plans/foo.md
/cursor-run --window .hermes "Composer 2.5 Fast" Review gateway.log for errors
/cursor-ask --window .hermes gpt-5.5 What changed in this repo?
```

### 自然语言

插件也能识别类似下面的飞书或 gateway 文本：

```text
Cursor 的 startell 窗口需要切换模型到 gpt
把 startell 切到 composer
切模型 gpt
startell 窗口用 gpt-5.5 帮我整理升级计划
hermes 项目切到 composer 2.5 fast 然后 review gateway log
让 Cursor 在 .hermes 工作区切换到 Composer 2.5 模型，然后问它“现在 hermes 升级计划是哪个模型生成的？”
```

## 迁移到另一台 Hermes 的建议清单

建议迁移这些内容：

```text
~/.hermes/skills/apple/cursor-applescript/
~/.hermes/plugins/cursor-automation/
~/.hermes/skills/apple/macos-computer-use/SKILL.md
```

其中 `macos-computer-use/SKILL.md` 不是插件运行的硬依赖，但建议同步，因为它包含 Cursor AppleScript 的 fallback 约定和使用注意事项。

不建议因为这次提交直接迁移这些文件：

- `cron/jobs.json`：包含本机 cron 运行状态、计数、飞书目标和绝对路径。
- `plans/hermes-upgrade-plan.md`：升级计划文档，不是 Cursor 自动化运行依赖。
- `reports/world_cup_2026_group_jkl_matchday3_analysis.md`：报告文件，不是 Cursor 自动化运行依赖。

## 目标机配置

目标机的 `~/.hermes/config.yaml` 需要启用插件：

```yaml
plugins:
  enabled:
    - cursor-automation
```

如果 `plugins.enabled` 已经存在，把 `cursor-automation` 加进去即可。

迁移后建议确认脚本权限：

```bash
chmod +x ~/.hermes/skills/apple/cursor-applescript/scripts/*.sh
python3 -m py_compile ~/.hermes/plugins/cursor-automation/*.py
```

然后重启 Hermes gateway，让插件重新加载。

## 目标机运行条件

- 系统必须是 macOS。
- Cursor 已安装并正在运行。
- Cursor 中已打开真实项目窗口，不只是 Settings 窗口。
- 运行 Hermes gateway 的进程需要 macOS「辅助功能」权限，通常是 `python`、Terminal、iTerm 或 launchd 启动项。
- Cursor 中需要已存在目标模型；AppleScript 只能搜索和选择模型，不能创建模型。
- 如果另一台机器的工作区不叫 `startell` 或 `.hermes`，需要修改 `plugins/cursor-automation/nl_parser.py` 里的 `WORKSPACE_ALIASES`。

## 迁移后验证

先确认 Cursor 窗口识别正常：

```bash
bash ~/.hermes/skills/apple/cursor-applescript/scripts/list_cursor_windows.sh
```

再测试模型切换：

```bash
bash ~/.hermes/skills/apple/cursor-applescript/scripts/switch_cursor_model.sh --window ".hermes" "gpt"
```

如果要测试完整 Composer 提交流程：

```bash
bash ~/.hermes/skills/apple/cursor-applescript/scripts/submit_cursor_composer.sh --window ".hermes" "gpt" "请总结当前项目结构"
```

## 常见问题

- 报 `Cursor is not running`：先启动 Cursor。
- 报 `Cursor Window menu not found`：确认 Cursor 是前台可访问应用；脚本已兼容英文 `Window` 和中文 `窗口`。
- 报 `No Cursor workspace matched query`：运行 `list_cursor_windows.sh`，使用 Window 菜单里的工作区文件夹名。
- 报 `Only Cursor Settings window found`：打开对应项目的主编辑窗口，不要只开 Settings。
- 报辅助功能或按键发送权限问题：给 Hermes gateway 所在进程开启 macOS 辅助功能权限。
- 文本误粘到代码文件：说明焦点不对，先在 Cursor 里撤销，再重新运行脚本；当前脚本已加入 `Escape`、`Cmd+1`、`Cmd+L` 降低这个风险。

## 参考过的本地规则

本次总结和迁移建议参考了：

- `~/.agents/skills/skill-router/SKILL.md`
- `~/.agents/skills/git-operations/SKILL.md`
