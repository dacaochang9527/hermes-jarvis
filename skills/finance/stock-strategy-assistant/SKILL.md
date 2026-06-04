---
name: stock-strategy-assistant
description: "设计和实现个人股票策略助手：选股规则化、回测、日报、盘中提醒与风控边界。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [stocks, quant, backtesting, alerts, finance, product]
    category: finance
---

# Stock Strategy Assistant 股票策略助手

本 skill 是股票策略助手的入口和路由，不保存屠龙细则。屠龙当前规则见 `references/tulong-current-rules.md`；运行、cron、切池、日志、微信投递和排障见 `references/tulong-operations.md`。

## 适用场景

当用户希望讨论、设计或实现以下系统时加载本 skill：

- 选股助手、股票监控、买卖信号提醒；
- A 股/港股/美股的中短线、波段、事件交易、量化筛选；
- 把口头战法/朋友策略/图片策略规则化；
- 回测某个选股策略或验证正反案例；
- 构建每日收盘报告、盘中提醒、风控/复盘系统。

## 安全边界

- 不输出“必须买/卖某只股票”“保证收益”等确定性投资建议。
- 输出策略信号，而不是交易指令；使用“观察、触发、失效、风险提示、复盘”等语言。
- 每个信号都要给出风控或失效条件。
- 先验证再实时化；未经验证的策略不要包装成确定机会。
- 盘中提醒优先限制在观察池/自选股，不做全市场噪音扫描。

## 通用工作流

1. 明确市场、风格、输出形式、数据源约束和股票池过滤边界。
2. 把口头策略拆成状态机、可执行条件、排除条件、风控/失效位和数据需求。
3. 优先做离线扫描和回测，验证样本、胜率、回撤、盈亏比和误报。
4. 再进入盘中提醒，只监控已确认观察池或持仓池。
5. 收盘后复盘提醒结果，沉淀有效、误报、漏选和规则修正。

优先把“主力”“洗盘”“强势”等主观词翻译为价格、量能、形态、时间窗口和可复盘条件。

## 数据源默认选择

- A 股 MVP 优先 `akshare`；需要稳定历史数据时可考虑 `tushare`；免费备选可用 `baostock`。
- 少量自选股盘中监控可用新浪行情接口，具体实现见 `references/tulong-operations.md`。
- 不要因为当前环境缺少 pytest、akshare、tushare token 等就写入长期负面结论；这类只是环境状态。

## 屠龙专题路由

当用户讨论“屠龙战术”、D1/D2/D3、D3观察区、HOLD 持仓、日期+D几、买点/失效位/参与区、规则输入修订时，从本 skill 主入口分流；不要先尝试加载旧的 `tulong-tactics` 子技能名。

加载：

```text
references/tulong-current-rules.md
```

当用户涉及脚本运行、D3 生成命令、实际监控池、preopen 切池/守门、cron、watchdog、日志、微信投递、限流、脚本目录、架构职责边界或 runtime/selection/src/reference 分工时，加载：

```text
references/tulong-operations.md
```

当用户发送当天买卖/成交截图，要求“整理到交易文档/交易流水/持仓记录”时，加载：

```text
references/tulong-trade-screenshot-entry.md
```

## 屠龙会话纪律

- 屠龙相关问题直接从本 skill 主入口分流到 `references/tulong-current-rules.md` / `references/tulong-operations.md`；不要先尝试旧名或子技能名 `tulong-tactics`，该入口在部分会话中不可见。
- 屠龙盘中提醒的事件分层、状态去重、飞书全量输出和验证口径见 `references/tulong-monitoring-discipline.md`。
- 当用户问“改完了吗 / 做了吗”时，必须区分“建议/判断”与“已落地并验证”。如果只是给过优化建议，不要暗示已经完成；应立即实现、运行验证，并说明验证结果。
- 盘中监控和提醒优化属于运行流程变更：除了改脚本，也要同步 `references/tulong-operations.md`，并至少跑 `py_compile` 与一次 `FORCE_RUN=1` 验证用户可见输出。

## 标准规则与朋友规则边界

- 用户只说“生成 MMDDD3”时，默认使用标准主规则，输出文件为 `MMDDD3_watch_scan_YYYYMMDD_HHMMSS.csv`。
- 用户明确说“按朋友规则 / new_strategy / new_strategy_full / 昨天那10只口径 / 做对照”时，才额外生成外部策略结果或做差异对照。
- 调整策略规则时，优先改动标准主规则（`generate_d3_candidates.py` 的 `score_candidate()` + 当前规则文档）；朋友规则先保持为外部策略输入/对照实验。
- 不要因为某天朋友规则表现较好就把它静默设成默认。吸收朋友规则有效部分应走正式规则变更协议：先在复盘确认，再修改标准主规则和同步各层。
- 当复盘结论是“标准规则负责不漏强，new_strategy_full 负责能不能做”这类权重重排时，默认处理为标准主规则吸收可参与性权重，而不是把外部策略设为默认；重点检查 active/radar 分层、`pool_subtype` 输出、preopen 只切 active、复盘归因拆分是否同步。
- D3 交易归因必须拆分为 D3 active、D3 radar、HOLD/T、策略外、ETF；当日 D3 策略胜率只统计 active 内交易，不混入 HOLD/T、策略外或 ETF。

## 维护纪律

- `SKILL.md` 只保留入口、边界和路由，不写屠龙细则。
- 新确认的屠龙规则写入 `references/tulong-current-rules.md`，并按其中“规则变更同步协议”评估 `src/stock_assistant/`、`scripts/tulong/selection/`、`scripts/tulong/runtime/`、`references/tulong-operations.md` 和测试是否需要同步修改。
- 当用户要求取消、替换或改名某个策略环节（例如窄化、校正、补票、HOLD 口径、提醒方式）时，按规则变更处理：同步当前规则、运行手册、脚本生成文案和守门测试；历史 `reports/` 只作为过去产物，除非用户明确要求，不批量回改。
- 新确认的运行流程、cron、切池、日志、提醒链路写入 `references/tulong-operations.md`。
- `references/` 只保留未来会话应主动加载的当前事实源；当用户反馈 skill 太乱、reference 太散或职责模糊时，先压缩入口、合并到现有 class-level reference，删除旧底稿/一次性笔记，而不是继续新增平级 reference。
- `scripts/tulong/README.md` 只维护脚本目录、入口和 wrapper 映射；运行流程、active 池来源、HOLD 派生、cron、watchdog、日志、排障纪律、脚本目录和架构职责边界统一维护在 `references/tulong-operations.md`，不要两边重复保存同一事实。
- 从 README 或其他局部文档移除跨层职责说明时，不要直接删除语义；先迁移到对应的 class-level reference（屠龙运行/架构职责默认进 `references/tulong-operations.md`），再在局部文档保留轻量索引或跳转。
- 修改屠龙策略规则时，把 `references/tulong-current-rules.md` 视为上游策略事实源，但必须按其中“规则变更同步协议”评估并同步 `src/stock_assistant/strategy_tulong.py`、`scripts/tulong/selection/`、`scripts/tulong/runtime/`、`references/tulong-operations.md` 和 tests；不要只改规则文档，也不要只做文档位置一致性检查。
- 对文档分层、职责迁移或规则同步机制做维护时，优先增加/更新轻量 pytest 守门测试，防止职责说明回流到局部 README、规则协议丢失、或 selection 脱离可复用规则模块。
- 单日复盘、迁移记录、旧策略底稿和一次性问题笔记不要新增为平级 reference；阶段性结论优先放到 `reports/reviews/`，只在当前 reference 中保留必要索引。
- 持仓事实源变更要同步三层：`references/tulong-current-rules.md`、`references/tulong-operations.md`、以及 `scripts/tulong/runtime/` 实际运行脚本和对应测试；不要只改文档。当前 HOLD 从 `data/trades/tulong_trades.csv` 的 buy/sell 流水派生 open position，不再维护独立 `HOLD_position_*` 源文件。
