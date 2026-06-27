---
name: cursor-applescript
description: |
  Drive Cursor IDE on macOS via AppleScript keyboard simulation: switch the
  Agent/Composer model (Cmd+/ search) and optionally paste a prompt into
  Composer. Use when the user asks to control Cursor from Hermes, switch
  Cursor models remotely, run Cursor Agent with a specific model name, or
  types /cursor-model or /cursor-run on gateway/Feishu/CLI. NOT Codex CLI.
  Load whenever the session specifies a target Cursor model (e.g. gpt-5.5,
  Composer 2.5 Fast) to select before submitting work.
version: 1.5.0
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [cursor, applescript, macos, ide, automation, composer, agent]
    category: desktop
    related_skills: [macos-computer-use]
prerequisites:
  platforms: [macos]
  apps: [Cursor]
---

# Cursor AppleScript Automation

Automate **Cursor IDE** (the Electron app) from Hermes using AppleScript +
keyboard simulation. This is **not** Codex CLI — do not route these requests
to `codex exec`.

## Session inputs (required)

Read from the **current user message**:

| Input | Required | Example |
|-------|----------|---------|
| `model` | **Yes** | `gpt-5.5`, `Composer 2.5 Fast`, `claude-4-opus` |
| `workspace` | No | `.hermes`, `startell`（工作区文件夹名，不是 Tab 标题） |
| `prompt` | No | Task to paste into Composer after switching model |

If the user only asks to switch model, run `switch_cursor_model.sh` only.
If they also want Cursor to execute a task, run `submit_cursor_composer.sh`.
**When the user names a Cursor window / workspace**（如「startell 窗口」「.hermes 那个项目」），
必须传 `--window` 或 `--workspace`（二者等价），值为**工作区文件夹名**。
先跑 `list_cursor_windows.sh` 看 Window 菜单里有哪些工作区；**不要**用 Tab 标题
（如 `Cursor Settings — startell`、`Git Graph — .hermes`）当 `--window` 参数。

## Gateway slash commands（直达脚本，不经 LLM）

`~/.hermes/plugins/cursor-automation` 插件注册 `/cursor-model` 与 `/cursor-run`。
飞书 / Telegram / CLI 输入这些命令时 **直接执行 shell 脚本**，不加载本 skill、
不消耗 LLM token。需在 `config.yaml` 启用：

```yaml
plugins:
  enabled:
    - cursor-automation
```

| Command | Args | 执行的脚本 |
|---------|------|-----------|
| `/cursor-model` | `[--window\|--workspace <name>] <model> [prompt]` | 仅模型 → `switch_cursor_model.sh`；带 prompt → `submit_cursor_composer.sh` |
| `/cursor-run` | `[--window\|--workspace <name>] <model> <prompt>` | `submit_cursor_composer.sh` |
| `/cursor-ask` | `[--window\|--workspace <name>] <model> <question>` | `ask_cursor_chat.sh`，切模型后向 Cursor Chat 提问 |

Examples:

```
/cursor-model gpt-5.5
/cursor-model --window startell gpt
/cursor-model --window .hermes gpt-5.5 Write upgrade plan to .hermes/plans/foo.md
/cursor-run --window .hermes "Composer 2.5 Fast" Review gateway.log for errors
```

`gpt` 等短名可直接作为 picker 搜索词，**不要**因名称模糊而追问用户。
解析规则：先读可选 `--window` / `--workspace`，**第一个参数 = model**，其余 = prompt。

### 自然语言（同样直达脚本，不经 LLM）

飞书里说人话即可，**不必记 slash 命令**。`cursor-automation` 插件会在
消息进 Agent 前识别意图，改写成 `/cursor-model` 或 `/cursor-run` 再执行。

示例（直接发文字，不要带 `/`）：

```
Cursor 的 startell 窗口需要切换模型到 gpt
把 startell 切到 composer
切模型 gpt
startell 窗口用 gpt-5.5 帮我整理升级计划
hermes 项目切到 composer 2.5 fast 然后 review gateway log
让 Cursor 在 .hermes 工作区切换到 Composer 2.5 模型，然后问它“现在hermes升级计划是哪个模型生成的？”
```

识别规则（确定性，不是 LLM）：

- 提到 **Cursor / 窗口 / 工作区 / 切模型** 等 + **模型名**（gpt、composer、claude…）
- 工作区名：`startell`、`.hermes`（Window 菜单文件夹名，不是 Tab 标题）
- 带「帮我 / 然后 / review …」等任务描述 → 自动走 `cursor-run`
- 带「问它 / 问 Cursor …」的问题 → 自动走 `cursor-ask`，不会再走 Composer 快捷键

其他聊天内容不受影响；只有匹配到 Cursor 控模意图才会拦截。

## Prerequisites

1. **macOS** with Cursor installed and **running**
2. **Accessibility** — 运行 `osascript` 的进程（通常是 **Hermes gateway** 的
   `python`，不是 Cursor）需在 **系统设置 → 隐私与安全 → 辅助功能** 中授权。
   若报错含 `不允许辅助访问` 或 `不允许发送按键 (1002)` 才是权限问题；若报错
   `不能获得 menu bar item "Window"` 则是菜单语言不匹配（中文系统用 **窗口**）。
3. **Model must exist in Cursor** — add custom models under Cursor Settings →
   Models before searching. AppleScript cannot create models; it only selects
   from the picker list via search.

## Bundled scripts

Resolve skill root from the loaded skill path, then:

```bash
SKILL_ROOT="${HERMES_SKILL_DIR:-$HOME/.hermes/skills/apple/cursor-applescript}"
SCRIPTS="${SKILL_ROOT}/scripts"
```

### 0. List open Cursor workspaces

```bash
bash "${SCRIPTS}/list_cursor_windows.sh"
```

输出 Window 菜单里的工作区列表（`*` = 当前前台工作区），以及当前 Tab 标题（仅供参考）。
切换脚本**只认工作区名**，不认 Tab 标题。

### 1. Switch model only (Scheme A)

```bash
bash "${SCRIPTS}/switch_cursor_model.sh" "gpt-5.5"
bash "${SCRIPTS}/switch_cursor_model.sh" --window ".hermes" "gpt-5.5"
```

Mechanism: **`focus_cursor_window.scpt`**（`--window` / `--workspace`）— 读 Cursor
**Window 菜单**（按工作区文件夹名列出）→ 精确/唯一模糊匹配 → 点击对应菜单项 →
校验勾选标记 → `Escape`×2 → **`Escape` + `Cmd+1`** → **`Cmd+L`** → **`Cmd+/`**
→ 粘贴模型名 → **Enter**。

即使用户在 startell 里打开了 Settings（Tab 标题 `Cursor Settings — startell`），
`--window startell` 仍会切到 **startell 工作区窗口**，不会误匹配 Settings Tab。

**Never send `Cmd+L` while the integrated terminal is focused** — Cursor auto-attaches
`@terminals/<id>.txt` to the chat/composer input (common when Feishu triggers
`/cursor-model` while the mouse is in the terminal panel).

**Never send `Cmd+/` while a code editor tab is focused** — in the editor it
toggles line comment and `Cmd+V` pastes into the open file (e.g. `config.yaml`).

### 2. Switch model + submit Composer prompt

```bash
bash "${SCRIPTS}/submit_cursor_composer.sh" "gpt-5.5" "Create upgrade plan at .hermes/plans/foo.md"
bash "${SCRIPTS}/submit_cursor_composer.sh" --window ".hermes" "gpt-5.5" "Create upgrade plan at .hermes/plans/foo.md"
```

For **Chinese or long prompts**, always pass via the script argument (uses
`pbcopy` + `Cmd+V`), never `keystroke` the prompt inline.

### 3. Read Cursor history from local databases

When the user asks "what did Cursor just do?" or "latest task in window X",
query Cursor's SQLite databases for Composer session history. See
`references/cursor-history.md` for the full query reference and examples.

```bash
# Quick check: list recent Composer sessions across all workspaces
sqlite3 "$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb" \
  "SELECT value FROM ItemTable WHERE key='composer.composerHeaders';" \
  | python3 -c '
import sys, json, datetime
data = json.loads(sys.stdin.buffer.read())
for c in sorted(data.get("allComposers", []),
       key=lambda x: x.get("lastUpdatedAt", 0), reverse=True)[:5]:
    ts = c.get("lastUpdatedAt", 0)
    dt = datetime.datetime.fromtimestamp(ts/1000)
    print(f"[{dt:%m-%d %H:%M}] {c.get(\"name\",\"\")}  ({c.get(\"filesChangedCount\",0)} files)")
'
```

## Agent workflow

```
1. Parse model name from user request (required)
2. Confirm Cursor is running
3. If user mentions a window / workspace / project → pass `--window` with folder name
4. If workspace unknown → list_cursor_windows.sh；**不要**再用 `every window of process Cursor` 猜工作区
5. User said model `gpt` → pass `"gpt"` to picker search as-is; do not block on asking GPT-4o vs 4.1 unless script fails
6. If only switching model → switch_cursor_model.sh [--window "$WS"] "$MODEL"
6. If also driving a task → submit_cursor_composer.sh [--window "$WS"] "$MODEL" "$PROMPT"
7. Tell user to verify model label in the target workspace
```

## When to use

- User says: switch Cursor to model X / 让 Cursor 用 gpt-5.5 / drive Cursor IDE
- Gateway or Feishu asks Hermes to delegate work to **Cursor** (not Codex CLI)
- Need model switch **before** Composer submission

## When NOT to use

| Situation | Use instead |
|-----------|-------------|
| Codex CLI / `codex exec` | `codex` skill + terminal |
| Background GUI without focus steal | `macos-computer-use` + `computer_use` |
| Direct file edits | `read_file` / `write_file` / `patch` |
| Cursor not installed / not running | Ask user to launch Cursor first |

## Limitations

- **No read-back** — AppleScript cannot read Cursor's bottom model label; verify
  manually or via screenshot (`screencapture`).
- **Workspace matching via Window menu** — `--window startell` 指工作区文件夹名，
  与当前 Tab 标题（Settings、Git Graph 等）无关。
- **Search-only** — relies on Cursor's model picker search (`Cmd+/`).
- **Fragile focus** — user must not type while the script runs.
- **Keyboard layout** — `Cmd+/` may differ on non-US layouts; US QWERTY assumed.
- **Separate from Codex CLI** — Cursor model ≠ `~/.codex/config.toml` model.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `不能获得 menu bar item "Window"` (-1728) | 中文 macOS 菜单是 **窗口** 不是 Window；v1.4.1 已修复。不是权限问题 |
| `不允许辅助访问` / `不允许发送按键 (1002)` | 才需要给 **Hermes gateway**（python）开辅助功能 |
| Model unchanged after script | Model not in Cursor list; use exact picker label |
| `No Cursor workspace matched query` | Run `list_cursor_windows.sh`; use folder name from Window menu |
| `Workspace query matched multiple` | Use exact name (e.g. `.hermes` not `hermes`) |
| `Failed to focus Cursor workspace` (-54) | Window menu click failed; ensure workspace is open in Cursor |
| Agent used Tab title as `--window` | Wrong — use `startell` not `Cursor Settings — startell` |
| **Text pasted into open file** | Editor had focus — **Cmd+Z** undo; script runs `Cmd+L` first |
| **Chat shows `@terminals/….txt`** | Terminal had focus — remove chip; script runs `Escape`+`Cmd+1` first |
| Prompt not submitted | Retry `submit_cursor_composer.sh`; Composer shortcut `Cmd+Shift+I` |

### Terminal focus attaches `@terminals/<id>.txt`
auto-attaches a terminal context chip to the Composer input. The fix is the
`Escape` + `Cmd+1` sequence that precedes `Cmd+L` (already built into
`switch_cursor_model.scpt`). If a stray `@terminals/` chip still appears,
the user should remove it manually.

## Reading Cursor history from local SQLite databases

Cursor stores Composer/Agent conversation history in SQLite databases on disk.
See `references/cursor-history.md` for the full query reference.

## Example (Feishu → Cursor)

User: `/cursor-model gpt-5.5 Write upgrade plan to plans/foo.md`

User: `/cursor-run --window .hermes gpt-5.5 Write upgrade plan to plans/foo.md`

Or natural language: 「用 AppleScript 让 Cursor 切到 gpt-5.5，然后写升级计划」

```bash
MODEL="gpt-5.5"
WINDOW=".hermes"
PROMPT='Create a detailed upgrade plan ... Write to .hermes/plans/foo.md'
bash "$HOME/.hermes/skills/apple/cursor-applescript/scripts/submit_cursor_composer.sh" --window "$WINDOW" "$MODEL" "$PROMPT"
```

Then reply: model search submitted; ask user to confirm bottom bar shows
gpt-5.5 before trusting the Agent output.
