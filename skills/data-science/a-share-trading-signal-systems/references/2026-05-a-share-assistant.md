# 2026-05 A 股选股助手实现经验

## 背景

用户要做本地 A 股中短线选股助手，核心是“屠龙战术”首板后 D1/D2/D3/D4/D5 状态机，并希望每日收盘扫描、盘中提醒、回测复盘。项目路径当时为：

```text
/Users/fenomenoronaldo/Documents/ai-project/a-share-stock-assistant
```

本记录保存可复用经验，不保存 token、账号、Cookie、交易资料等敏感信息。

## 架构经验

推荐先做本地 Python CLI，而不是 Web App：

- `DailyBar` 统一数据模型；
- `DailyDataProvider` 统一数据源接口；
- 策略模块只依赖 `DailyBar`；
- `scanner.py` 做收盘扫描；
- `backtest.py` 做状态机回放；
- `intraday_monitor.py` 做盘中提醒；
- `journal.py` 做复盘日志。

这样可以快速切换 AkShare、Tushare、CSV、东方财富 JSON 导入等来源。

## 数据源经验

### 东方财富

现象：普通浏览器能打开 `push2his.eastmoney.com` 历史 K 线 JSON，但 Python/CLI/curl_cffi/Playwright 在当时环境中均可能遇到：

- `RemoteDisconnected`
- `ProxyError`
- `curl: (56) Connection closed abruptly`
- `curl: (52) Empty reply from server`
- `Page.goto: net::ERR_EMPTY_RESPONSE`

处理方式：不要要求用户提供东方财富账号密码、交易密码、Cookie 或 session。历史 K 线通常不应依赖登录态。可改用：

1. 浏览器 JSON 手工导入；
2. AkShare 新浪日线；
3. Tushare（如果有权限）。

### Tushare

token 应通过 `.env` 或环境变量 `TUSHARE_TOKEN` 注入，且 `.env` 加入 `.gitignore`。

当时验证发现 token 可读取，但账号没有：

- `daily`
- `stock_basic`

接口权限。报错类似：

```text
抱歉，您没有接口(daily)访问权限
```

这表示不是代码读取 token 失败，而是账号权限不足。

### AkShare 新浪源

`akshare.stock_zh_a_daily` 在当时可用，足够支持历史日线、D1/D2/D3 扫描和回测。

验证过正反案例：

- 佳力图 `603912`：符合 D1/D2 后进入 D3 观察；
- 天安新材 `603725`：D2 成交量超过 D1 两倍，被排除。

注意：AkShare 东方财富历史 K 线 `stock_zh_a_hist` 可能仍会受东方财富链路影响；不要和新浪日线源混淆。

## 屠龙战术规则落地

MVP 规则：

- D1：首板，今日涨停、昨日非涨停、日内非完全一字；
- D2：冲高回落；成交量/D1 不超过 2；收盘不破 D1 支撑；
- D3：观察水下低吸机会；跌破 D1 支撑策略失效；
- D4/D5：按规则管理，避免持仓幻想。

D1 支撑 MVP：

```text
max(D1.open, D1.prev_close)
```

可选加入最近平台高点。

## 快速扫描技巧

全市场逐只拉历史 K 线很慢，并且并发使用 AkShare 可能触发底层 JS/V8 相关崩溃或不稳定。更稳妥的流程：

1. `ak.stock_zt_pool_em(date='D1日期YYYYMMDD')` 获取 D1 涨停池；
2. 过滤主板、非 ST/退市、连板数为 1；
3. 只对剩余股票用 `stock_zh_a_daily` 拉取 D1/D2 附近历史；
4. 应用 `is_d1_first_board` 和 `is_d2_pullback`；
5. 用成交额、量比、回落幅度、失效位距离排序。

一次扫描例子：

- D1：2026-05-21 周四；
- D2：2026-05-22 周五；
- D3：2026-05-25 周一。

筛出观察池：

```text
600578 京能电力
600936 北投科技
003007 直真科技
603373 安邦护卫
```

输出时强调这是 D3 观察池，不是直接买入清单。

## 候选池输出字段

建议固定输出：

- 代码/名称；
- D2 收盘；
- D3 观察价；
- 失效位；
- D2 量比；
- D2 冲高幅度；
- D2 高点回落幅度；
- D2 成交额；
- 简短排序理由和风险提示。

## 合规/表达边界

推荐话术：

- “重点观察池”；
- “水下承接”；
- “跌破失效位移除”；
- “不是直接买入清单”。

避免：

- “可以买”；
- “必涨”；
- “保证收益”；
- “确定性买点”。
