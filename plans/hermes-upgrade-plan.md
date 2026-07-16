# Hermes Agent 升级计划

> 创建日期：2026-06-27  
> 当前版本：**v0.13.0** (v2026.5.7)  
> 目标版本：**v0.17.0** (v2026.6.19) — [GitHub Latest Release](https://github.com/NousResearch/hermes-agent/releases/latest)  
> 环境：`~/.hermes` · macOS · Python 3.11.15 · OpenAI SDK 2.24.0

---

## 执行摘要

| 项目 | 值 |
|------|-----|
| 版本跨度 | v0.13.0 → v0.14.0 → v0.15.x → v0.16.0 → **v0.17.0**（4 个 minor + 2 patch） |
| 时间跨度 | 2026-05-07 → 2026-06-19（约 6 周） |
| 上游变更规模（v0.16→v0.17） | ~800 PR · 1,693 files · +235,390 / -50,730 行 |
| 本机代码来源 | **Fork**：`dacaochang9527/hermes-jarvis`（非上游直装） |
| 活跃 Cron | **9** 个任务（全部 `enabled`，多数 `no_agent: true` 脚本任务） |
| 主要投递通道 | Feishu 投递 + Weixin 来源会话 |
| 配置版本 | `_config_version: 23`（doctor 报告与 v0.13.0 一致） |
| 磁盘余量 | ~141 GB 可用（充足） |

**结论**：功能收益大（桌面端、后台子代理、memory 批量编辑、Feishu/Weixin 网关加固、Automation Blueprints 等），但存在若干**行为级 breaking change**；且本机使用 **fork 仓库 + 自定义 finance skill**，不能无脑 `hermes update`，必须先制定合并/备份策略。

---

## 1. 版本路线图

| 版本 | Tag | 发布日期 | 代号 / 主题 |
|------|-----|----------|-------------|
| **当前** v0.13.0 | v2026.5.7 | 2026-05-07 | The Tenacity Release — Kanban 耐久板、Checkpoints v2、`no_agent` cron |
| v0.14.0 | v2026.5.16 | 2026-05-16 | 性能与平台扩展 — OpenRouter Pareto、`huggingface/skills` tap、i18n 16 语言 |
| v0.15.0 | v2026.5.28 | 2026-05-28 | The Velocity Release — `run_agent.py` 大重构、Kanban swarm、`session_search` 重写 |
| v0.15.1 / v0.15.2 | v2026.5.29 / .29.2 | 2026-05-29 | Patch — 稳定性修复 |
| v0.16.0 | v2026.6.5 | 2026-06-05 | The Surface Release — **桌面端首发**、Dashboard 管理面板、默认 skill 精简 |
| **目标** v0.17.0 | v2026.6.19 | 2026-06-19 | The Reach Release — Photon iMessage、Raft、后台子代理、Automation Blueprints |

---

## 2. 本机环境清单（升级前快照）

### 2.1 安装与代码

```text
hermes --version  →  Hermes Agent v0.13.0 (2026.5.7)
Project           →  /Users/fenomenoronaldo/.hermes/hermes-agent
Remote origin     →  git@github.com:dacaochang9527/hermes-jarvis.git
最近本地 commit   →  feat(futures-trading-assistant): 增强 PVC 监控…（含 gateway / 飞书发布等定制）
```

> ⚠️ **关键风险**：代码树是 fork，含 futures-trading-assistant、gateway 中间消息、飞书单次发布等定制。上游 `hermes update` 或 `git checkout v2026.6.19` 会覆盖或冲突这些改动。

### 2.2 模型与辅助任务

| 配置项 | 当前值 | 升级注意 |
|--------|--------|----------|
| `model.default` | `deepseek/deepseek-v4-flash` + provider `deepseek` | doctor 警告 slug 格式；v0.16+ 模型 picker 行为变化 |
| `compression.codex_gpt55_autoraise` | `true` | 与 v0.17 压缩策略一致，升级后观察上下文占用 |
| `delegation.child_timeout_seconds` | `600` | v0.17 **移除默认子代理 wall-clock 超时**；本机显式配置仍有效 |

### 2.3 Gateway / Cron（业务关键）

**Cron 任务（9 个，全部 enabled）**：

| 名称 | 类型 | 投递 |
|------|------|------|
| A股屠龙D3盘中监控 | `no_agent` + script | feishu |
| A股屠龙D3四股收盘复盘 | `no_agent` + script | feishu |
| A股屠龙D3开盘前切池 | `no_agent` + script | feishu |
| A股屠龙D3开盘前守门校验 | `no_agent` + script | feishu |
| PVC2609期货事件监控 | script/cron | feishu |
| PVC2609期货半小时简报 | script/cron | feishu |
| PVC2609期货开盘前守门校验 | script/cron | feishu |
| PVC2609期货夜盘开盘前守门校验 | script/cron | feishu |
| A股集合竞价行业板块汇总 | script/cron | feishu |

**影响评估**：多数为 `no_agent: true` 脚本任务，**不依赖 LLM 工具行为**，主要风险在：

1. cron 调度器 / gateway 投递链路
2. Feishu / Weixin 适配器内部重构
3. 配置 schema 迁移导致 gateway 启动失败

### 2.4 目录体量

| 路径 | 大小 |
|------|------|
| `~/.hermes/hermes-agent` | ~601 MB |
| `~/.hermes/skills` | ~618 MB |
| `~/.hermes/sessions` | ~155 MB |

---

## 3. Breaking Changes 与行为变更（按严重度）

### 🔴 高 — 可能直接影响本机工作流

#### 3.1 移除 agent 可调用的 `send_message` 工具（v0.17.0）

- **变更**：模型不再能通过工具主动发消息；gateway 回复、cron deliver、平台原生投递仍正常。
- **本机影响**：
  - `skills/finance/stock-strategy-assistant/references/tulong-operations.md` 仍引用 `send_message(target="feishu")`
  - `skills/autonomous-ai-agents/hermes-agent/` 多处 Weixin/Feishu 排障文档依赖 `send_message`
- **升级后动作**：升级后首轮对话测试「发到飞书」类指令；必要时改 skill 文档/流程为 gateway 自然回复或 cron deliver，而非工具调用。

#### 3.2 Feishu 审批按钮 fail-closed（v0.17.0）

- **变更**：Slack / **Feishu** / Discord 在未配置 allowlist 时，审批按钮认证 **fail closed**（更安全，可能阻断未配置场景）。
- **本机影响**：Feishu 是主要 cron 投递通道；若使用交互式审批需确认 allowlist / webhook secret。
- **关联（v0.15.0）**：Feishu 要求 webhook auth secret + honor config extras。
- **升级后动作**：检查 Feishu 应用 webhook 配置与 `config.yaml` 中 Feishu 相关项；升级后发送测试消息 + 触发一次需审批的工具调用。

#### 3.3 Weixin 速率限制熔断器（v0.17.0）

- **变更**：Weixin 适配器新增 rate-limit circuit breaker。
- **本机影响**：cron + 聊天 + 工具消息叠加时，Weixin 通道可能更 aggressively 限流（skill 文档已有 ilink 限流说明）。
- **升级后动作**：升级后 24h 内观察 `~/.hermes/logs/gateway.log` 中 weixin 相关 ERROR；避免同一时段多源并发推送。

#### 3.4 Fork 代码与上游分叉（本机特有）

- **变更**：上游 4 个 minor 版本含 gateway/run.py、cli.py、run_agent.py 大规模重构。
- **本机影响**：fork 上 gateway 中间消息、PVC 报告发布等定制与 upstream v2026.6.19 **必然冲突**。
- **升级后动作**：见 §5 升级路径选择，**禁止**未备份、未合并策略下直接 checkout 上游 tag。

#### 3.5 `write_mode` → `write_approval`（v0.17.0）

- **变更**：三元 `write_mode` 改为布尔 `write_approval`（默认 off）。
- **本机影响**：若曾自定义 memory/skill 写入审批，需迁移配置键。
- **升级后动作**：`hermes config migrate` 后 diff `config.yaml`。

---

### 🟡 中 — 功能行为变化，需验证

#### 3.6 `session_search` 完全重写（v0.15.0）

- 移除 `mode` 参数与 aux-LLM 路径；改为 discovery / scroll / browse 推断模式。
- 本机 `auxiliary.session_search` 配置仍存在但行为已变；**无 LLM 成本，更快**。
- 若 skill 或脚本硬编码旧 API 参数，需更新。

#### 3.7 默认 bundled skill 精简（v0.16.0）

移除或改为 optional：`spotify`、`linear`、`kanban-codex-lane`、`debugging-hermes-tui-commands` 等。  
本机 finance skill 在 `~/.hermes/skills/`，**不受影响**；仅当依赖某 bundled skill 时需 `hermes skills install`。

#### 3.8 Curator consolidation 改为 opt-in（v0.17.0）

- **变更**：`curator.consolidate` 默认 **false**；仅 prune 仍默认开启。
- **本机**：`curator.enabled: true`，`interval_hours: 168` — 升级后 routine curation **不再消耗 aux-model token**（符合预期）。
- 若需要 umbrella skill 合并：设置 `curator.consolidate: true` 或 `hermes curator run --consolidate`。

#### 3.9 子代理默认超时移除（v0.17.0）

- 上游移除 default subagent wall-clock timeout。
- 本机 `delegation.child_timeout_seconds: 600` 仍保留显式上限，风险较低。

#### 3.10 `read_file` 输出格式（v0.16.0）

- compact line-number gutter 成为**唯一**格式（约少 14% token）。
- 不影响功能，但依赖精确行号对齐的旧 prompt/skill 可能需微调。

#### 3.11 Dashboard 认证加强（v0.16–v0.17）

- OAuth gate、401 on token endpoints、websocket auth 变更。
- 若使用 Dashboard 远程访问，升级后需重新 login / register OAuth client。

#### 3.12 Cron per-job profile 被 revert（v0.17.0，未 ship）

- 不要依赖该功能；多 profile cron 仍按 v0.16 行为。

---

### 🟢 低 — 新增配置项 / 向后兼容

| 新增 / 变更 area | 说明 |
|------------------|------|
| `automation_blueprints` | v0.17 蓝图化定时任务（可选） |
| `desktop` | v0.16+ 桌面端配置 |
| `photon` | v0.17 iMessage via Photon（本机未用可忽略） |
| `display.language` | v0.16 桌面/i18n；当前 `en` |
| `curator.consolidate` | v0.17 新增，默认 false |
| `managed scope` / fleet | v0.17 团队部署（本机单用户可忽略） |
| Bitwarden Secrets Manager | v0.15 可选，替代 `.env` 明文 key |
| Nous Portal JWT-only | v0.16 移除 legacy session-key inference |

**兼容项（官方声明/实测 v0.13 基线）**：

- 核心 `AIAgent` 接口保持
- `delegate_task` 签名向下兼容（v0.17 新增 `background=true`）
- Skill 格式 `SKILL.md` 不变
- Session 存储格式兼容
- `no_agent` cron 模式保持

---

## 4. 各版本 Highlights（与本机相关性）

### v0.14.0 — 值得知道

- OpenRouter Pareto + `min_coding_score`（本机已配 `openrouter.min_coding_score: 0.65`）
- `huggingface/skills` 默认 tap
- Gateway + Dashboard i18n 扩展至 16 语言
- `/goal` checklist 部分 revert（`/subgoal` 简化回归）

### v0.15.0 — 值得知道

- `run_agent.py` 16k → 3.8k 行（`agent/*` 模块）
- Kanban swarm / 104 PR 多代理 maturation
- Promptware / Brainworm 防御
- xAI 模型退役检测 → `hermes migrate xai`
- ntfy 第 23  messaging platform
- MCP Nous-approved catalog + interactive picker

### v0.16.0 — 值得知道

- **Hermes Desktop** 原生应用（macOS 一键安装 + 应用内更新）
- Dashboard 全功能管理面板（Channels / MCP / Credentials）
- Quick Setup via Nous Portal
- `/undo [N]` 撤回最近 N 轮
- 默认 skill 精简 + curator 可 prune bundled skills
- CVE-2026-48710 Starlette pin 安全修复

### v0.17.0 — 值得知道

- Background subagents：`delegate_task(background=true)`
- `memory` 工具 atomic batch `operations`
- Automation Blueprints（免 cron 语法）
- `grok-composer-2.5-fast` via xAI OAuth
- Photon iMessage、Raft 网络、WhatsApp Business Cloud API
- Telegram Bot API 10.1 rich messages（默认开启）
- Skills Hub 安全扫描 + Featured
- 大规模 god-file refactor（cli / gateway / run_agent）

---

## 5. 升级路径选择

### 路径 A — 上游纯净升级（仅当可放弃 fork 定制）

适用：fork 定制已合并到 `~/.hermes/skills/` 且不再需要 hermes-agent 源码内改动。

```bash
# 添加 upstream（若尚未添加）
cd ~/.hermes/hermes-agent
git remote add upstream https://github.com/NousResearch/hermes-agent.git
git fetch upstream --tags

# 备份后切换
git checkout v2026.6.19
source .venv/bin/activate
pip install -e ".[all]"   # 或按现有 install 方式
```

### 路径 B — Fork 合并升级（**推荐本机**）

适用：保留 `hermes-jarvis` 上 gateway / futures-trading-assistant 等定制。

```bash
cd ~/.hermes/hermes-agent
git remote add upstream https://github.com/NousResearch/hermes-agent.git  # 若未有
git fetch upstream --tags

# 在独立分支合并
git checkout -b upgrade/v0.17.0
git merge upstream/v2026.6.19   # 或 git rebase upstream/v2026.6.19

# 解决冲突（重点关注）：
#   gateway/run.py 及 mixins
#   gateway/platforms/feishu.py, weixin.py
#   hermes_cli/
#   agent/
#   skills/finance/futures-trading-assistant/（若在源码树内）

source .venv/bin/activate
pip install -e .
hermes doctor --fix
```

### 路径 C — `hermes update` 一键升级

```bash
hermes update
```

- 官方推荐路径，会拉 upstream 并处理依赖。
- **本机风险**：若 update 指向 upstream 而非 fork，**会丢失** hermes-agent 目录内未 push 的定制；执行前必须完成 §6 备份，并确认 update 源。

---

## 6. 升级步骤（详细）

### 阶段 0 — 选窗口

| 规则 | 说明 |
|------|------|
| **避开 A 股交易时段** | 9:15–15:00（cron 盘中监控密集） |
| **避开夜盘前校验窗口** | PVC 夜盘任务 schedule 前 30 分钟 |
| **建议时间** | 周末、节假日、或 15:30 后 / 21:00 前 |
| **监控期** | 升级后至少 **24–48h** 观察 cron + gateway |

### 阶段 1 — 备份（必做）

```bash
STAMP=$(date +%Y%m%d_%H%M)

# 配置与密钥
cp ~/.hermes/config.yaml ~/.hermes/config.yaml.bak.$STAMP
cp ~/.hermes/.env ~/.hermes/.env.bak.$STAMP
cp ~/.hermes/auth.json ~/.hermes/auth.json.bak.$STAMP 2>/dev/null || true

# Cron 与状态
cp ~/.hermes/cron/jobs.json ~/.hermes/cron/jobs.json.bak.$STAMP
cp ~/.hermes/state.db ~/.hermes/state.db.bak.$STAMP

# Skills（用户数据）
tar czf ~/hermes-skills-backup-$STAMP.tar.gz -C ~/.hermes skills

# 代码树（含 fork 定制）
tar czf ~/hermes-agent-backup-$STAMP.tar.gz -C ~/.hermes hermes-agent

# 可选：profile 导出
hermes profile export default -o ~/hermes-profile-backup-$STAMP.tar.gz
```

### 阶段 2 — 升级前快照

```bash
hermes --version > ~/hermes-pre-upgrade-version.txt
hermes gateway status | tee ~/hermes-pre-upgrade-gateway.txt
hermes cron list | tee ~/hermes-pre-upgrade-cron.txt
hermes config check | tee ~/hermes-pre-upgrade-config-check.txt
hermes doctor | tee ~/hermes-pre-upgrade-doctor.txt

# 记录 gateway log 尾部
tail -200 ~/.hermes/logs/gateway.log > ~/hermes-pre-upgrade-gateway-log.txt
```

### 阶段 3 — 停止服务

```bash
hermes gateway stop
# 确认无残留 hermes gateway 进程
pgrep -fl "hermes.*gateway" || echo "gateway stopped"
```

### 阶段 4 — 执行升级

按 §5 选择路径 A / B / C 之一执行。

**依赖与桌面端（可选）**：

```bash
hermes doctor --fix
# 若需桌面端（v0.16+）
# hermes desktop install   # 或从 release 安装 macOS app
```

### 阶段 5 — 配置迁移

```bash
hermes config check
hermes config migrate
hermes doctor --fix
```

**预期新增/迁移项（按需手工确认）**：

```yaml
# 示例：v0.17 curator（若不 consolidate 可省略）
curator:
  consolidate: false   # 默认即可

# 若启用桌面端
# desktop: { ... }

# 若将来用 Automation Blueprints
# automation_blueprints: { ... }
```

**本机 Feishu display 配置**（已有，升级后保留）：

```yaml
display:
  platforms:
    feishu:
      tool_progress: "off"
      interim_assistant_messages: false
      streaming: false
```

### 阶段 6 — 重启与冒烟测试

```bash
hermes gateway start
hermes gateway status
hermes cron status
hermes cron list

# CLI 冒烟
hermes chat -q "Hello，升级后连通性测试"

# 手动触发一个低风险 cron（选非交易时段任务）
hermes cron run <job-id>
```

---

## 7. 升级后验证清单

### 7.1 基础

- [ ] `hermes --version` → **v0.17.0 (v2026.6.19)**
- [ ] `hermes config check` 无 ERROR
- [ ] `hermes doctor --fix` 关键项通过
- [ ] `config.yaml` 中 `_config_version` 已递增
- [ ] Fork 定制功能仍可用（PVC 报告、飞书发布脚本等）

### 7.2 Gateway

- [ ] `hermes gateway status` → running
- [ ] Feishu：发送测试消息，收到回复
- [ ] Weixin：发送测试消息（注意限流熔断）
- [ ] `gateway.log` 无持续 ERROR / traceback
- [ ] 交互式工具审批（若使用）在 Feishu 正常

### 7.3 Cron（业务关键）

- [ ] `hermes cron list` → 9 个任务均在，schedule 正确
- [ ] 至少手动 `hermes cron run` 一次 **no_agent** 任务
- [ ] 验证 feishu deliver 成功（`last_status: ok`）
- [ ] 下一交易日 9:00 前：开盘前守门校验任务正常
- [ ] PVC 夜盘 / 半小时简报 schedule 未漂移

### 7.4 Skills / 工具

- [ ] `hermes skills list` 含 finance 相关 skill
- [ ] `/skill` 加载 stock-strategy-assistant / futures-trading-assistant
- [ ] Memory 读写正常（`MEMORY.md` / `USER.md`）
- [ ] 确认 agent **不再调用** `send_message`；飞书同步改走对话回复或脚本 deliver
- [ ] `delegate_task` 正常；可选测 `background=true`

### 7.5 可选新功能

- [ ] Desktop app 启动（若安装）
- [ ] Dashboard 登录（若使用远程 admin）
- [ ] Automation Blueprints 浏览：`hermes cron` / dashboard

---

## 8. 回滚策略

### 8.1 完全回滚

```bash
hermes gateway stop

# 恢复配置
STAMP=<你的备份时间戳>
cp ~/.hermes/config.yaml.bak.$STAMP ~/.hermes/config.yaml
cp ~/.hermes/.env.bak.$STAMP ~/.hermes/.env
cp ~/.hermes/cron/jobs.json.bak.$STAMP ~/.hermes/cron/jobs.json
cp ~/.hermes/state.db.bak.$STAMP ~/.hermes/state.db

# 恢复代码
cd ~/.hermes/hermes-agent
git checkout main          # 或升级前 commit/tag
source .venv/bin/activate
pip install -e .

# 恢复 skills（若被覆盖）
tar xzf ~/hermes-skills-backup-$STAMP.tar.gz -C ~/.hermes

hermes gateway start
hermes cron list
hermes cron run <critical-job-id>
```

### 8.2 部分回滚（仅 gateway 异常）

```bash
tail -300 ~/.hermes/logs/gateway.log
hermes gateway restart
# 若 Feishu/Weixin 单独故障：检查平台 credential + webhook secret
hermes debug   # 收集诊断后再提 Issue
```

### 8.3 中止条件

出现以下情况**立即停止进一步变更**，执行回滚：

1. Gateway 无法启动且 15 分钟内无法修复
2. Cron 连续 2 次 `last_status: error` 于交易相关任务
3. Feishu deliver 全面失败
4. `hermes update` / merge  mid-flight 失败导致代码树不可安装

---

## 9. 升级后维护建议

1. **更新 skill 文档**：将 `send_message` 相关指引改为 gateway 回复 / cron deliver 模式。
2. **观察 Weixin 限流**：升级后一周内减少并发通知源。
3. **Curator**：保持默认 `consolidate: false` 除非确实需要 umbrella merge。
4. **定期对齐 upstream**：fork 建议每 1–2 个 minor 版本 rebase，避免再次累积 4 版本冲突。
5. **启用 pre-update backup**：可考虑 `updates.pre_update_backup: true`（当前为 false）。

---

## 10. 参考链接

| 资源 | URL |
|------|-----|
| Latest Release | https://github.com/NousResearch/hermes-agent/releases/latest |
| v0.17.0 Notes | https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.19 |
| v0.16.0 Notes | https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.5 |
| v0.15.0 Notes | https://github.com/NousResearch/hermes-agent/releases/tag/v2026.5.28 |
| v0.14.0 Notes | https://github.com/NousResearch/hermes-agent/releases/tag/v2026.5.16 |
| v0.13.0 Notes（当前） | https://github.com/NousResearch/hermes-agent/releases/tag/v2026.5.7 |
| 官方升级指南 | https://hermes-agent.nousresearch.com/docs/user-guide/updating |
| GitHub Issues | https://github.com/NousResearch/hermes-agent/issues |

---

## 附录 A — 建议执行命令速查

```bash
# 一键前检查
hermes --version && hermes doctor && hermes gateway status && hermes cron list

# 推荐升级（fork 合并后）
cd ~/.hermes/hermes-agent && pip install -e . && hermes config migrate && hermes doctor --fix

# 升级后确认
hermes --version && hermes config check && hermes gateway status && hermes cron status
```

## 附录 B — 本计划未自动执行项

- 未执行实际 `hermes update` / git merge（仅规划）
- 未修改 `config.yaml` / cron / gateway 运行态
- upstream fetch 因网络可能较慢，合并前请在本地确认 `git fetch upstream --tags` 完成
