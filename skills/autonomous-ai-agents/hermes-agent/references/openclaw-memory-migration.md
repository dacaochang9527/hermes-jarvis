# OpenClaw → Hermes 记忆迁移审核要点

用于审核从 `~/.openclaw` 迁移到 Hermes 的长期记忆方案。目标不是全量搬家，而是把旧系统资料分流到 memory、skills、config/setup 或 drop。

## 推荐扫描范围

优先看：
- `~/.openclaw/workspace/USER.md`：用户画像。
- `~/.openclaw/workspace/MEMORY.md`：长期记忆，但通常混有旧系统配置和秘密。
- `~/.openclaw/workspace/SOUL.md`：可提炼用户偏好的助手风格，不要原样迁移为身份设定。
- `~/.openclaw/workspace/CORE_RULES.md`：通常是执行/核验规则的精简可靠来源。
- `~/.openclaw/workspace/memory/*.md`：只抽取反复出现、仍会改变行为的教训。
- 专项目录如 `memory/stocks/`、`scripts/read-article/`、`memory/feishu-automation.md`：多半应进入 REVIEW 或 skill，而不是普通 memory。

跳过或仅作证据，不迁移：
- `node_modules/`、logs、sessions、media、browser user-data、package lock、运行截图。
- credentials、device pairing、cookies、tokens、allow lists、channel/user identifiers。

## 分流规则

### 放入 Hermes USER memory

只放稳定用户画像：称呼、时区、默认语言、风格偏好、协作偏好。

例：
- 用户昵称 Cc，时区 Asia/Shanghai。
- 用户默认偏好中文。
- 用户偏好冷静、稳定、JARVIS 式助手。
- 用户希望助手通过对话和确认逐步学习判断标准。

### 放入 Hermes MEMORY

只放短、稳定、会改变行为的规则：
- 执行闭环：说已执行必须真的执行；承诺不是结果；多步任务先做一段再汇报。
- 事实核验：时间、数量、状态、版本、是否发生过等先查证。
- 用户可见完成：后台任务成功不等于用户看见结果。
- 用户专属词汇：例如“风模式/海模式”的简明定义。
- 自动化偏好摘要：复杂浏览器/新标签/文档编辑优先脚本或 Playwright。

### 写成 skill

程序化流程和排障知识优先写成 skill，memory 只留触发摘要：
- 飞书文档自动化：URL 规则、selector 策略、contenteditable、hover 菜单、分享确认、调试截图。
- 深度文章分析/海模式：原文读取、实体提取、外部搜索、综合输出。
- 浏览器自动化：Playwright 脚本优先、稳定 selector、失败不擅自换路线。
- 投资记录框架：如果用户确认长期使用，可成为专题记录/分析 skill；不要自动迁入普通 memory。

### 保持 REVIEW

需要用户明确确认后再迁移：
- 每条回复顶部时间戳。
- iMessage/BlueBubbles 或 Feishu channel 接管。
- 心跳/cron 主动提醒频率。
- 旧 Mark 1/Mark 2 工作流在 Hermes 中的重新映射。
- MacBook 远程待机实践。
- 金融/投资策略，尤其具体交易法。

### DROP

不要迁移：
- 旧 OpenClaw provider/model/gateway/heartbeat 事故细节，除非提炼成通用执行教训。
- Chrome relay token、gateway token、derived token、cookies、Feishu user id、BlueBubbles API password、iMessage service id。
- 旧版本回退命令、安装噪音、运行日志、历史 sessions。

## 审核提示

- 不要把旧 OpenClaw 的“人格文件”原样覆盖 Hermes persona；提炼为用户偏好即可。
- `CORE_RULES.md` 常比长篇 `MEMORY.md` 更适合作为最终 wording 来源。
- 看到具体标识符、邮箱、service id、`ou_...`、token/cookie/path-to-auth-file 时，默认不进 memory。
- 原方案如果说某专题“都是模板”，仍要检索是否存在散落在日记里的具体内容；金融类内容尤其要单独 REVIEW。
- 如果当前 Hermes memory 文件不存在，要在最终草案里明确说明无法做内容去重，并按 fresh final content 生成；不要暗示已和现有内容合并。
- 用户明确从 REVIEW 中移除的项目，应从后续 summary、skill 候选和最终可写入内容里同步移除，避免“去除了但仍在别处推荐”。
- 用户明确保留的 REVIEW 项要转成短、稳定、会改变行为的 MEMORY wording；例如顶部时间戳偏好、主动 check-in 频率和“后台成功不等于用户可见”。
- 最终可写入版本可以参考 `references/openclaw-memory-migration-final-draft-case.md` 的结构。
