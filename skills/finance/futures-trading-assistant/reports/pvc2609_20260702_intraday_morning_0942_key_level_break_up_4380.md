# PVC2609 2026-07-02 上午盘盘中关键位触发操作重估

> 生成时间：2026-07-02 09:42 CST  
> 飞书在线文档：https://mcncgf38by7m.feishu.cn/docx/RUAAdMGOdoHDBfxajfUcpatsnAf  
> 标的：PVC2609 期货合约  
> 触发来源：reports/pvc2609_20260702_intraday_morning_0912_key_level_break_down_4390.md  
> 数据源：新浪期货公开 quote、3m/15m/30m K线、本地关键位状态  
> 数据状态：quote 返回 `2026-07-02 09:42:19`，现价 `4382`，quote 日期与交易日不一致：否  
> 风险提示：本文为盘中条件化操作重估，不构成确定性投资建议；没有触发确认就观望。

## 1. 触发概况

| 项目 | 内容 |
|---|---|
| 触发时段 | 上午盘 |
| 触发时间 | 2026-07-02 09:45:00 |
| 触发价位 | 4380 |
| 触发类型 | key_level_break_up |
| 触发说明 | 3m收盘收回/上破 4380（触发后短线中轴） |
| 触发后现价 | 4382 |
| 本时段第几份盘中文档 | 2/3 |

## 2. 当前结构

| 周期 | 区间 | 收盘/现价 | 量仓 | 解读 |
|---|---|---|---|---|
| 3m 本时段 | 4368-4416 | 4381 | 量 149515；持仓变化 14552 | 入场触发周期，只看有效收线 |
| 15m 本时段 | 4370-4416 | 4379 | 量 142970；持仓变化 8204 | 判断触发是否有连续性 |
| 30m 本时段 | 4370-4416 | 4379 | 量 141710；持仓变化 2414 | 判断是否只是短线噪音 |

## 3. 操作概率表

| 方案 | 条件 | 概率 | 处理 | 失效 | 目标 |
|---|---|---:|---|---|---|
| A 修复延续 | 回踩 4380/4385 不破 | 36%-44% | 等待回踩不破再考虑多 | 跌回 4380 | 先看 4395，再看 4405 |
| B 冲高回落 | 上冲 4395 后不能站稳 | 26%-34% | 多单降级，观察承压 | 站稳 4405 | 回看 4385/4380 |
| C 中轴震荡 | 价格回到 4380-4395 内反复 | 18%-25% | 不追单，只等边界 | 突破/跌破边界 | 无固定目标 |
| D 修复失败 | 跌回 4380 | 10%-16% | 修复逻辑失效，等反抽不过 | 重新站回 4385 | 看 4370 |

## 4. 新关键位

| 新关键位 | 类型 | 含义 | 再触发是否发文档 |
|---:|---|---|---|
| 4380 | support | 回踩不破确认位 | 是，受时段上限约束 |
| 4385 | midline | 触发后短线中轴 | 是，受时段上限约束 |
| 4395 | resistance | 上方第一压力 | 是，受时段上限约束 |
| 4405 | repair_confirmation | 修复延续确认位 | 是，受时段上限约束 |
| 4370 | failure_confirmation | 修复失败确认位 | 是，受时段上限约束 |

## 5. 最终口径

- 这次只说明 `3m收盘收回/上破 4380（触发后短线中轴）` 已经发生，不代表必须立刻交易。
- 下一步优先看新关键位表前三项；同一价位附近 `5` 点内不重复生成文档。
- 如果价格回到中轴反复，按横盘陷阱处理，宁可少做，不要让盘中链接刷屏。
- 每个时段最多生成 `3` 份盘中重估文档。

```text
STATE_HANDOFF
contract: PVC2609
source_doc: reports/pvc2609_20260702_intraday_morning_0942_key_level_break_up_4380.md
session_completed: intraday_morning
next_session: intraday_followup
bias: up
risk_flags: intraday_trigger, one_level_quote_only, no_tick_active_flow, max_reports_3
must_watch_levels:
  - price: 4380
    role: support
    label: 回踩不破确认位
    trigger: effective_3m_close
  - price: 4385
    role: midline
    label: 触发后短线中轴
    trigger: effective_3m_close
  - price: 4395
    role: resistance
    label: 上方第一压力
    trigger: effective_3m_close
  - price: 4405
    role: repair_confirmation
    label: 修复延续确认位
    trigger: effective_3m_close
  - price: 4370
    role: failure_confirmation
    label: 修复失败确认位
    trigger: effective_3m_close
monitor_levels_updated: true
```
