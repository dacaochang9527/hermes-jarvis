---
name: a-share-trading-signal-systems
description: 构建和验证 A 股本地选股/交易信号系统：免费行情源、策略状态机、回测、日报、盘中提醒与凭证安全。
---

# A 股交易信号系统

## 适用场景

当用户要做 A 股选股、短线/波段策略验证、涨停板战法、每日收盘扫描、盘中提醒、回测复盘，或需要接入免费/付费 A 股数据源时，使用本技能。

目标是帮助用户构建**可验证的本地信号系统**，而不是给出确定性荐股或保证收益的交易指令。

## 基本原则

1. **先定义边界**
   - 输出“策略信号、候选池、观察价、失效位、风险提示、复盘结果”。
   - 不输出“保证买入/卖出”“必涨”“确定收益”等表达。
   - 明确最终交易由用户自行判断。

2. **数据源优先级**
   - 免费历史日线优先尝试 AkShare 新浪源：`stock_zh_a_daily`。
   - 涨停池/首板池可用 AkShare 东方财富涨停池接口，例如 `stock_zt_pool_em(date='YYYYMMDD')`，即使东方财富 K 线直连不可用，涨停池接口可能仍可用。
   - Tushare token 必须通过环境变量或未跟踪 `.env` 注入，不要写入代码、README、报告或聊天总结。
   - 东方财富公开 K 线接口如在 CLI/自动化环境被断开，不要反复死磕；可改为浏览器 JSON 导入或换免费源。

3. **凭证安全**
   - 不保存、不打印、不复述用户的券商账号、交易密码、Cookie、session、token。
   - `.env` / `config/local.yaml` 必须加入 `.gitignore`。
   - 聊天和报告中把 token 写作 `[REDACTED]`。

4. **验证优先**
   - 每接一个数据源，至少做字段映射单元测试和一个真实股票案例检查。
   - 每改策略，跑测试和最小真实样本回测。
   - 对日期、交易日、D1/D2/D3 对应关系必须用工具确认，不能凭记忆。

## 推荐实现结构

本地 Python CLI 项目可包含：

```text
config/
  strategy.yaml
  universe.yaml
  alert.yaml
src/<package>/
  models.py
  indicators.py
  data_provider.py
  akshare_provider.py
  tushare_provider.py
  strategy_tulong.py
  strategy_swing.py
  scanner.py
  backtest.py
  intraday_monitor.py
  reporter.py
  journal.py
tests/
reports/
backtests/
```

统一抽象建议：

- `DailyBar`：代码、名称、交易日、开高低收、昨收、成交量、成交额、涨跌幅、换手率、涨停价。
- `DailyDataProvider`：`stock_codes()` 和 `history(code, start, end)`。
- 策略函数只依赖统一 `DailyBar`，不要绑定具体数据源。

## 数据源接入要点

### AkShare 新浪日线

- 函数：`ak.stock_zh_a_daily(symbol='sh600000', start_date='YYYYMMDD', end_date='YYYYMMDD', adjust='')`
- 代码转换：
  - `6/5/9` 开头通常用 `sh`；
  - 其他常见 A 股用 `sz`。
- 常见字段：`date/open/high/low/close/volume/amount/turnover`。
- `turnover` 在不同源中单位可能不同，接入时写测试确认。

### Tushare

- 从 `.env` 或环境变量读取 `TUSHARE_TOKEN`。
- 代码转换：
  - `603912` → `603912.SH`
  - `000001` → `000001.SZ`
- `daily` 常用字段：`trade_date/open/high/low/close/pre_close/vol/amount/pct_chg`。
- `amount` 通常是千元单位，内部如统一用元，需要乘以 `1000`。
- 如果返回“没有接口访问权限”，说明 token 可读但账号权限不足；切换免费源或让用户开通权限。

### 新浪实时行情轻量验证

可直接请求：

```python
import requests
url = 'https://hq.sinajs.cn/list=sh600578,sz003007'
headers = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}
text = requests.get(url, headers=headers, timeout=20).text
```

这适合少量股票盘中验证，不适合作为完整历史回测源。

## 屠龙战术状态机示例

把“首板后 D1/D2/D3/D4/D5”写成状态机，而不是一次性主观判断。

- D1：首板；可要求今日涨停、昨日非涨停、日内曾打开/非一字。
- D2：冲高回落，成交量不超过 D1 的 2 倍，不能跌破 D1 支撑。
- D3：水下观察日，只观察低开/水下承接，跌破 D1 支撑则失效。
- D4：按高开/平开/低开和是否破支撑管理。
- D5：除非大行情或策略另有规则，否则强制退出观察/持有状态。

D1 支撑位 MVP 可先用：

```text
max(D1.open, D1.prev_close, optional_recent_platform_high)
```

有分钟线后再优化“主力拉升前位置”。

## 扫描效率技巧

不要一开始就逐只拉全市场历史 K 线。对涨停板战法，优先：

1. 用涨停池接口获取 D1 当日涨停列表。
2. 用涨停池字段过滤首板/连板数、ST、北交所、创业板/科创板等。
3. 只对剩余几十只股票拉历史日线做 D2 判断。
4. 再按成交额、量比、回落幅度、失效位距离排序。

这比扫 3000+ 只股票快得多，也更稳定。

## 输出格式建议

给用户候选池时，保持简洁、可执行：

```text
代码 名称
D2收盘：x.xx
D3观察价：x.xx 附近或水下
失效位：x.xx
D2量比：x.xx
D2冲高：x.x%
D2高点回落：x.x%
D2成交额：x.xx亿
风险提示：...
```

同时强调：这不是直接买入清单，而是“观察池”。

## 常见坑

- 不要把东方财富账号登录态作为历史 K 线的默认方案；公开行情接口通常不该要求用户提供敏感登录资料。
- 不要把某个数据源一次失败写成永久结论；记录可复现的替代路径即可。
- 不要泄露 token 到报告、README、测试快照、命令输出。
- 不要用未来数据做回测或 D3 观察判断。
- 不要在非交易日/节假日硬推 D1/D2/D3；先确认交易日。

## 参考资料

- `references/2026-05-a-share-assistant.md`：一次完整的 A 股选股助手实现经验，包括 Tushare 权限不足、AkShare 新浪源跑通、屠龙战术 D1/D2/D3 扫描和候选池格式。