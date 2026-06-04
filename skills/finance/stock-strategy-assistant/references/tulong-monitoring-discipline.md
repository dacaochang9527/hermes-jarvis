# 屠龙盘中提醒纪律

本文件只作为 `references/tulong-operations.md` 盘中提醒章节展开的细化参考，运行兜底仍以 operations.md 为准。

## 事件分层与推送规则

watchdog 事件分为 A/B/C 三层，记录在 `EVENT_TIERS`，当前已落地 `scripts/tulong/runtime/watchdog.py`。

### A 级：直接推送

```text
invalid           D3 跌破失效
near_invalid      D3 接近失效
entry_zone        D3 进入买点区
recover_trigger   D3 从水下回收观察价
hold_invalid      HOLD 跌破止损
hold_near_invalid HOLD 接近止损
hold_recover_cost HOLD 回收成本观察线
```

以上任一事件发生即推送；同状态不重复推。

### B 级：状态变化才推

```text
underwater_cross  D3 首次跌破观察价（必须接近买点区，远离买点的普通水下只写本地）
strong_up         D3 强势不追（涨幅≥7% 且高于观察价3%以上）
intraday_fade     D3 冲高回落（盘中高点涨幅≥8% 且回落≥4%）
sharp_down        D3 快速走弱
hold_cost_loss    HOLD 跌破成本观察线
hold_profit_take  HOLD 浮盈拉开（相对成本浮盈≥6% 或 涨幅≥5%且高于成本）
```

### C 级：只写本地

```text
underwater        普通水下（price < trigger 但不接近买点区，或非首次）
observe           普通观察
同状态重复        连续同一状态不下发
```

## 状态去重

- `alert_statuses` 字典按 code 记录上一轮状态。
- 同 code + 同 status 不重复推送。
- 状态从 `observe/underwater` 变到 `entry_zone/near_invalid/invalid/recover_trigger` → 重新推送。
- HOLD 的状态独立管理：`cost_loss` / `recover_cost` / `near_invalid` / `invalid` / `profit_take`。

## 输出格式

飞书投递，每轮含摘要头 + 单股块：

```text
【A股监控】0604 10:15｜推送7只｜A5 / B2
状态：买点区5｜HOLD跌破成本1｜HOLD浮盈观察1
优先看：002876 三利谱、600114 东睦股份、600160 巨化股份

0604D3 | 002876 三利谱 | 光学光电 | 买点区
现价 31.08 (+0.03%) | 买点 30.60–31.16 | 止损 27.72
动作：只等回到买点区/回收31.07；跌破27.72放弃
参考：距止损+12.1% | 成交额1.96亿 | 11:30
```

## 验证

修改 watchdog 提醒逻辑后必须：

1. `py_compile scripts/tulong/runtime/watchdog.py`
2. 清空 monitor state 的 `last_prices` / `alert_statuses` 做首次判断
3. `FORCE_RUN=1` 跑两轮：第一轮应有推送，第二轮应为 0（同状态去重生效）
4. 检查飞书实际推送不出现旧限流提示
