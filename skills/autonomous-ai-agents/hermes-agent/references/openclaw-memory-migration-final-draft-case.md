# OpenClaw → Hermes 记忆迁移：最终草案生成案例

本参考记录一次完整迁移审核流程的可复用产物形态，用于未来处理类似“从 OpenClaw 迁移到 Hermes memory”的任务。

## 本次新增经验

1. 当前 Hermes memory 文件可能不存在。
   - 检查 `~/.hermes/memories/USER.md` 和 `~/.hermes/memories/MEMORY.md`。
   - 如果不存在，不要假装已经做过去重；在最终草案里明确说明“未发现现有文件，因此按 fresh final content 生成”。

2. 用户可能会逐步裁剪 REVIEW 项。
   - 用户明确去除的项应从“待确认”降级为“本轮明确排除”。
   - 相关 skill 候选也要同步移除或标明不在范围内，例如用户排除 investment tracking 后，不再建议创建 `investment-tracking-framework`。

3. 用户确认保留的 REVIEW 项要进入最终 MEMORY wording。
   - 顶部时间戳偏好可写成：`User wants every visible assistant reply to start with the current timestamp in YYYY-MM-DD HH:MM:SS format.`
   - 主动 heartbeat/check-in 可写成：用户希望保留主动检查；30 分钟过频，倾向约每小时或更低频；后台成功不等于用户可见。
   - 旧 OpenClaw heartbeat/channel routing 细节不要迁移，只保留用 Hermes-native cron/gateway 配置的原则。

4. 最终输出应分成“可写入 memory”和“不要写入 memory”。
   - `USER.md` section：只放用户画像。
   - `MEMORY.md` section：只放行为偏好、执行闭环、核验、模式定义、主动检查偏好。
   - Skills section：只列未来可建 skill，不作为普通 memory。
   - Excluded section：记录用户明确排除项和敏感/旧系统资料。

## 推荐最终文件名

- 审核草案：`~/Desktop/hermes-memory-migration-final-draft.md`
- 最终可写入版本：`~/Desktop/hermes-memory-migration-ready-to-write.md`

## 最终可写入版本的推荐结构

```markdown
# Hermes Memory Migration - Ready-to-Write Version

Mode: final write draft only. This file has NOT been written to ~/.hermes/memories/.

Current Hermes memory check:
- ~/.hermes/memories/USER.md was/was not found.
- ~/.hermes/memories/MEMORY.md was/was not found.
- Deduplication result.

Cc confirmed these REVIEW items should be kept:
- ...

Cc removed these items from migration scope:
- ...

## 1. Final content for ~/.hermes/memories/USER.md

```markdown
...
```

## 2. Final content for ~/.hermes/memories/MEMORY.md

```markdown
...
```

## 3. Not included in memory, but approved as possible future skills

...

## 4. Explicitly excluded from this migration pass

...

## 5. Suggested write procedure when Cc approves actual migration

...
```

## Pitfalls

- 不要把 REVIEW 里被用户移除的项继续留在 summary 或 skill 候选里。
- 不要把 Feishu channel setup 和 Feishu document automation 混在一起；前者是配置/渠道接管，后者可以是流程型 skill。
- 不要把旧 OpenClaw 的 channel target、service id、cookie、token、pairing、allowlist 写入草案 memory。
- 生成最终草案时要修掉 Markdown fence 错误；尤其是用脚本写多层 code fence 时容易多一个结尾 ```。
