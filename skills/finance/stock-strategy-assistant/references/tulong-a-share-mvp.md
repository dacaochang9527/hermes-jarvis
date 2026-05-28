# 屠龙战术 A 股 MVP 参考

## 来源场景

用户希望做一个从自身兴趣/日常问题出发的创业/工具项目，提出需要 A 股、中短线波段、收盘日报 + 盘中提醒，并提供朋友的“屠龙战术”口头规则。该内容适合作为股票策略助手类任务的参考案例。

## 原始规则摘要

1. 第一天：盘中突然强势拉升首板，在通达信里找昨日首板再筛选。
2. 第二天：走势要冲高回落，最好低开、上午冲高、下午回落。
   - 不要找高开低走：可能是主力开始出货。
   - 第二天成交量最多是第一天两倍，再多不安全。
   - 反面教材：天安新材 603725，2023-07-28 周五，主力拉高出货。
   - 正面教材：佳力图 603912，2022-12-29 周四。
3. 第三天：买点必须在水下，上午 10 点左右通常出现最低位；如果低开很多，可以开盘买。
4. 第四天：卖或做 T。
   - 高开很多，马上卖，不贪心。
   - 平开震荡，等待拉高后卖。
   - 低开但不低于第一日主力拉升前位置，可根据均线考虑做 T。
   - 如果低于第一日主力拉升前位置，割肉离场，不做 T。
   - 除非遇上大行情，可以考虑卖半仓，否则清仓。
5. 第五天：除非遇上大行情，否则清全仓。

第三日是否适合买入的判断因素：

- 第二天成交量最多是第一天两倍；
- 日均线向上；
- EXPMA 在两个趋势线上方；
- DK 点处于 D 状态；
- 有合适机会才出手，不要天天出手。

## 规则化版本

### 状态机

```text
D1 首板发现
  → D2 冲高回落筛选
  → D3 水下观察
  → D4 止盈/止损/退出
  → D5 强制清仓
```

### D1 首板识别

日线 MVP 近似：

```text
close >= limit_up_price * 0.995
前一日未涨停
low < limit_up_price * 0.98   # 排除一字板
非 ST
成交额 > 1 亿
```

### D2 冲高回落筛选

必须满足：

```text
D2 开盘涨幅 <= 3%~4%
D2 最高价 > D2 开盘价 * 1.02
D2 收盘价 < D2 最高价 * 0.98
D2 成交量 <= D1 成交量 * 2
D2 收盘价 >= D1 支撑位
```

排除：

```text
D2 高开 > 4% 且收盘低于开盘
D2 成交量 > D1 * 2
高位巨量长上影
跌破 D1 支撑位
```

### D1 支撑位近似

“第一日主力拉升前位置”需要分钟线。日线 MVP 可近似为：

```text
D1_support = max(D1.open, D1.prev_close, 最近5日平台高点)
```

后续接分钟线后再替换为 D1 拉升前横盘区间。

### D3 水下观察

提醒条件：

```text
股票来自 D2 合格候选池
当前价 < D2 收盘价
当前涨跌幅 < 0
当前价 >= D1_support
时间优先 09:50–10:30
没有恐慌放量下杀
```

提醒语言应是“进入 D3 水下观察区”，不要说“必须买”。

### D4/D5 退出

D4：

- 高开超过 4%：提示按策略止盈/减仓；
- 平开震荡：提示拉高卖出观察；
- 跌破 D1_support：策略失效，提示退出，不做 T。

D5：

- 除非涨停/极强行情，否则提示策略窗口结束、原则上退出。

## MVP 项目结构

推荐项目名：`a-share-stock-assistant`。

```text
a-share-stock-assistant/
├── config/
│   ├── universe.yaml
│   ├── strategy.yaml
│   └── alert.yaml
├── data/
│   ├── raw/
│   ├── processed/
│   └── watchlists/
├── src/stock_assistant/
│   ├── data_provider.py
│   ├── indicators.py
│   ├── strategy_tulong.py
│   ├── strategy_swing.py
│   ├── risk_filter.py
│   ├── scanner.py
│   ├── intraday_monitor.py
│   ├── reporter.py
│   └── notifier.py
├── reports/daily/
├── backtests/tulong_backtest.py
├── tests/
├── README.md
├── docs-plan.md
└── pyproject.toml
```

## 配置模板要点

`strategy.yaml` 应包含：

```yaml
market:
  exclude_st: true
  exclude_beijing_exchange: true
  min_avg_turnover_20d: 100000000
  min_price: 3

tulong:
  d2:
    max_volume_ratio_to_d1: 2.0
    max_open_gap: 0.04
    min_high_above_open: 0.02
    min_close_below_high: 0.02
  d3:
    require_underwater: true
    preferred_time_start: "09:50"
    preferred_time_end: "10:30"
  exit:
    d4_high_open_take_profit: 0.04
    force_exit_day: 5
```

## 回测优先事项

先验证：

1. D2 过滤是否能排除“拉高出货”；
2. D3 水下买入后，D4/D5 的收益分布；
3. 弱市/退潮期是否需要关闭策略；
4. 正反案例是否符合规则解释：
   - 天安新材 603725，2023-07-28：应被排除或风险高；
   - 佳力图 603912，2022-12-29：应能通过核心过滤。

## 盘中提醒原则

只监控：

- 前一日 D2 合格、今日 D3 的屠龙候选；
- 已在观察池的波段候选；
- 用户手动加入的自选股。

轮询 3–5 分钟即可，不要一开始做 Tick 级系统。

## 典型提醒文案

```text
【屠龙 D3 观察】
股票：XXXX
当前价：xx
当前涨跌幅：-2.1%
D1 支撑位：xx
D2/D1 成交量比：1.45
状态：水下，未破支撑
风险：若跌破 xx，策略失效
```

```text
【屠龙策略失效】
当前价跌破 D1 支撑位，按策略应退出，不做 T。
```
