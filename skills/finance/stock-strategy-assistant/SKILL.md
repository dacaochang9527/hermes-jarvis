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

当用户讨论“屠龙战术”、D1/D2/D3、D3观察区、HOLD 持仓、日期+D几、人工补票、买点/失效位/参与区时，加载：

```text
references/tulong-current-rules.md
```

当用户涉及脚本运行、D3 生成命令、实际监控池、preopen 切池/守门、cron、watchdog、日志、微信投递、限流或排障时，加载：

```text
references/tulong-operations.md
```

## 维护纪律

- `SKILL.md` 只保留入口、边界和路由，不写屠龙细则。
- 新确认的屠龙规则写入 `references/tulong-current-rules.md`。
- 新确认的运行流程、cron、切池、日志、提醒链路写入 `references/tulong-operations.md`。
- `references/` 只保留未来会话应主动加载的当前事实源；当用户反馈 skill 太乱、reference 太散或职责模糊时，先压缩入口、合并到现有 class-level reference，删除旧底稿/一次性笔记，而不是继续新增平级 reference。
- 单日复盘、迁移记录、旧策略底稿和一次性问题笔记不要新增为平级 reference；阶段性结论优先放到 `reports/reviews/`，只在当前 reference 中保留必要索引。
