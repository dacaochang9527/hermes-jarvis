# PVC2609 2026-06-29 午盘盘中关键位触发操作重估

> 生成时间：2026-06-29 13:37 CST  
> 飞书在线文档：https://mcncgf38by7m.feishu.cn/docx/Hnu8dWdczoVaCKx4XQbc3AQCn5c  
> 标的：PVC2609 期货合约  
> 触发来源：reports/pvc2609_20260629_afternoon_preopen_review_forecast.md  
> 数据源：新浪期货公开 quote、3m/15m/30m K线、本地关键位状态  
> 数据状态：quote 返回 `2026-06-29 13:36:50`，现价 `4388`，quote 日期与交易日不一致：否  
> 风险提示：本文为盘中条件化操作重估，不构成确定性投资建议；没有触发确认就观望。

## 1. 触发概况

| 项目 | 内容 |
|---|---|
| 触发时段 | 午盘 |
| 触发时间 | 2026-06-29 13:36:00 |
| 触发价位 | 4390 |
| 触发类型 | key_level_break_down |
| 触发说明 | 3m收盘跌破 4390（压力区下沿/承压观察） |
| 触发后现价 | 4388 |
| 本时段第几份盘中文档 | 1/3 |

## 2. 当前结构

| 周期 | 区间 | 收盘/现价 | 量仓 | 解读 |
|---|---|---|---|---|
| 3m 本时段 | 4378-4393 | 4383 | 量 27025；持仓变化 -1593 | 入场触发周期，只看有效收线 |
| 15m 本时段 | 4378-4393 | 4383 | 量 27190；持仓变化 0 | 判断触发是否有连续性 |
| 30m 本时段 | 4378-4393 | 4383 | 量 50304；持仓变化 0 | 判断是否只是短线噪音 |

## 3. 操作概率表

| 方案 | 条件 | 概率 | 处理 | 失效 | 目标 |
|---|---|---:|---|---|---|
| A 弱势延续 | 反抽 4390/4385 不过 | 38%-45% | 等待反抽不过再考虑空 | 重新站回 4390 | 先看 4380，再看 4370 |
| B 假跌破收回 | 跌破后快速收回 4385 | 25%-32% | 空单降级，观察修复 | 再次跌回 4380 | 看 4390/4400 |
| C 中轴震荡 | 价格回到 4380-4390 内反复 | 18%-25% | 不追单，只等边界 | 突破/跌破边界 | 无固定目标 |
| D 强修复 | 站回 4400 | 10%-16% | 停止死空，按修复处理 | 跌回 4385 | 看上方新压力 |

## 4. 新关键位

| 新关键位 | 类型 | 含义 | 再触发是否发文档 |
|---:|---|---|---|
| 4370 | breakdown_target | 跌破后下方延伸确认 | 是，受时段上限约束 |
| 4380 | support | 盘中近端防守/假破观察 | 是，受时段上限约束 |
| 4385 | midline | 触发后短线中轴 | 是，受时段上限约束 |
| 4390 | retest_resistance | 反抽不过确认位 | 是，受时段上限约束 |
| 4400 | repair_confirmation | 重新修复确认位 | 是，受时段上限约束 |

## 5. 最终口径

- 这次只说明 `3m收盘跌破 4390（压力区下沿/承压观察）` 已经发生，不代表必须立刻交易。
- 下一步优先看新关键位表前三项；同一价位附近 `5` 点内不重复生成文档。
- 如果价格回到中轴反复，按横盘陷阱处理，宁可少做，不要让盘中链接刷屏。
- 每个时段最多生成 `3` 份盘中重估文档。

```text
STATE_HANDOFF
contract: PVC2609
source_doc: reports/pvc2609_20260629_intraday_afternoon_1337_key_level_break_down_4390.md
session_completed: intraday_afternoon
next_session: intraday_followup
bias: down
risk_flags: intraday_trigger, one_level_quote_only, no_tick_active_flow, max_reports_3
must_watch_levels:
  - price: 4370
    role: breakdown_target
    label: 跌破后下方延伸确认
    trigger: effective_3m_close
  - price: 4380
    role: support
    label: 盘中近端防守/假破观察
    trigger: effective_3m_close
  - price: 4385
    role: midline
    label: 触发后短线中轴
    trigger: effective_3m_close
  - price: 4390
    role: retest_resistance
    label: 反抽不过确认位
    trigger: effective_3m_close
  - price: 4400
    role: repair_confirmation
    label: 重新修复确认位
    trigger: effective_3m_close
monitor_levels_updated: true
```
