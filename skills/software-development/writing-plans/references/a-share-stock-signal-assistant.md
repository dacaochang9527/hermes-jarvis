# A 股选股/量化信号助手项目经验

## 场景

用户想把一个个人投资/选股策略做成自用工具：例如 A 股中短线波段、首板后低吸策略、盘中提醒、回测与复盘。

## 产品边界

- 不输出“保证买/卖”“一定收益”“替用户交易”等结论。
- 输出候选池、策略信号、触发价、失效价、风险提示、回测/复盘数据。
- 明确最终买卖由用户自行判断。

## 推荐 MVP 架构

```text
数据源 -> 指标计算 -> 策略筛选 -> 候选池 -> 盘中监控 -> 提醒 -> 复盘/周报
```

模块建议：

- `data_provider.py`：CSV、akshare、东方财富直连、tushare 等数据源接口。
- `indicators.py`：MA、EXPMA、滚动高点、涨停判断。
- `strategy_<name>.py`：策略规则化。
- `scanner.py`：收盘扫描。
- `backtest.py`：历史回测。
- `intraday_monitor.py`：盘中提醒。
- `journal.py` / `weekly_review.py`：复盘日志和周报。

## 屠龙战术规则化要点

状态机：

```text
D1 首板 -> D2 冲高回落筛选 -> D3 水下观察 -> D4 止盈/止损 -> D5 强制退出
```

关键条件：

- D1：当日涨停，前一日未涨停，非一字板。
- D2：冲高回落但非高开低走，成交量不超过 D1 的 2 倍，未跌破 D1 支撑位。
- D3：只在水下观察，跌破 D1 支撑位则失效。
- D4/D5：严格退出管理，避免短线策略套成长线。

D1 支撑位在无分钟数据时可近似为：

```text
max(D1.open, D1.prev_close, 近5日平台高点)
```

## 东方财富历史 K 线接口经验

浏览器可直接访问类似：

```text
https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=0&secid=1.603912&beg=20221215&end=20221221
```

返回 JSON 中：

- `data.preKPrice`：第一根 K 线昨收。
- `data.klines` 每行格式：

```text
日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
```

- `secid` 前缀：沪市常用 `1.`，深市常用 `0.`。

注意：浏览器能访问不代表 Python `requests` 能稳定访问；可能被 TLS 指纹/请求特征拦截。优先尝试：

1. 使用 `requests.Session(); session.trust_env = False` 绕过系统代理；
2. 加浏览器 UA/Referer；
3. 如果仍 `RemoteDisconnected`，改用 `curl_cffi` 的 `impersonate="chrome"`；
4. 或支持用户粘贴/导入浏览器 JSON、本地 CSV。

## 安全边界

不要索要或保存用户的东方财富账号密码、短信验证码、交易密码、完整 Cookie、交易 token。历史 K 线公开 JSON 通常不需要登录态。若必须用登录态，要求用户提供只读小号、最小 Cookie，并提醒用后注销。

## 验证建议

- 用用户提供的 JSON 样本写 parser 单测。
- 用 pytest 验证策略函数、回测、提醒去重、复盘周报。
- 若环境没有 pytest，先用纯 Python smoke test；装好依赖后补跑 pytest。
