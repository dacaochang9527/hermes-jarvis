# PVC2609 2026-07-10 夜盘盘中关键位触发操作重估

> 生成时间：2026-07-10 22:06 CST  
> 飞书在线文档：https://mcncgf38by7m.feishu.cn/docx/OBb5d1SIwosj0AxtgAZchkADnkf  
> 标的：PVC2609 期货合约  
> 触发来源：reports/pvc2609_20260710_night_preopen_review_forecast.md  
> 数据源：新浪期货公开 quote、3m/15m/30m K线、本地关键位状态  
> 数据状态：quote 返回 `2026-07-10 22:06:02`，现价 `4531`，quote 日期与交易日不一致：否  
> 风险提示：本文为盘中条件化操作重估，不构成确定性投资建议；没有触发确认就观望。

## 1. 触发概况

| 项目 | 内容 |
|---|---|
| 触发时段 | 夜盘 |
| 触发时间 | 2026-07-10 22:06:00 |
| 触发价位 | 4535 |
| 触发类型 | key_level_break_down |
| 触发说明 | 3m收盘跌破 4535（短线中轴下沿） |
| 触发后现价 | 4531 |
| 本时段第几份盘中文档 | 1/3 |

## 2. 当前结构

| 周期 | 区间 | 收盘/现价 | 量仓 | 解读 |
|---|---|---|---|---|
| 3m 本时段 | 4515-4541 | 4530 | 量 6716；持仓变化 3905 | 入场触发周期，只看有效收线 |
| 15m 本时段 | 4515-4541 | 4530 | 量 2003；持仓变化 241 | 判断触发是否有连续性 |
| 30m 本时段 | 4515-4541 | 4528 | 量 1384；持仓变化 -2041 | 判断是否只是短线噪音 |

## 3. 操作概率表

| 方案 | 条件 | 概率 | 处理 | 失效 | 目标 |
|---|---|---:|---|---|---|
| A 弱势延续 | 反抽 4545/4535 不过 | 38%-45% | 等待反抽不过再考虑空 | 重新站回 4545 | 先看 4530，再看 4520 |
| B 假跌破收回 | 跌破后快速收回 4535 | 25%-32% | 空单降级，观察修复 | 再次跌回 4530 | 看 4545/4555 |
| C 中轴震荡 | 价格回到 4530-4545 内反复 | 18%-25% | 不追单，只等边界 | 突破/跌破边界 | 无固定目标 |
| D 强修复 | 站回 4555 | 10%-16% | 停止死空，按修复处理 | 跌回 4535 | 看上方新压力 |

## 4. 新关键位

| 新关键位 | 类型 | 含义 | 再触发是否发文档 |
|---:|---|---|---|
| 4520 | breakdown_target | 跌破后下方延伸确认 | 是，受时段上限约束 |
| 4530 | support | 盘中近端防守/假破观察 | 是，受时段上限约束 |
| 4535 | midline | 触发后短线中轴 | 是，受时段上限约束 |
| 4545 | retest_resistance | 反抽不过确认位 | 是，受时段上限约束 |
| 4555 | repair_confirmation | 重新修复确认位 | 是，受时段上限约束 |

## 5. 最终口径

- 这次只说明 `3m收盘跌破 4535（短线中轴下沿）` 已经发生，不代表必须立刻交易。
- 下一步优先看新关键位表前三项；同一价位附近 `5` 点内不重复生成文档。
- 如果价格回到中轴反复，按横盘陷阱处理，宁可少做，不要让盘中链接刷屏。
- 每个时段最多生成 `3` 份盘中重估文档。

```text
STATE_HANDOFF
contract: PVC2609
source_doc: reports/pvc2609_20260710_intraday_night_2206_key_level_break_down_4535.md
session_completed: intraday_night
next_session: intraday_followup
bias: down
risk_flags: intraday_trigger, one_level_quote_only, no_tick_active_flow, max_reports_3
must_watch_levels:
  - price: 4520
    role: breakdown_target
    label: 跌破后下方延伸确认
    trigger: effective_3m_close
  - price: 4530
    role: support
    label: 盘中近端防守/假破观察
    trigger: effective_3m_close
  - price: 4535
    role: midline
    label: 触发后短线中轴
    trigger: effective_3m_close
  - price: 4545
    role: retest_resistance
    label: 反抽不过确认位
    trigger: effective_3m_close
  - price: 4555
    role: repair_confirmation
    label: 重新修复确认位
    trigger: effective_3m_close
monitor_levels_updated: true
```
