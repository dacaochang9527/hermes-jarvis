# A 股数据源与接口验证笔记

本参考来自一次构建个人 A 股中短线选股助手的实践，重点记录可复用的数据源经验。

## 东方财富公开 K 线 JSON

浏览器 URL 示例：

```text
https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=0&secid=1.603912&beg=20221215&end=20221221
```

返回结构：

```json
{
  "rc": 0,
  "data": {
    "code": "603912",
    "market": 1,
    "name": "佳力图",
    "preKPrice": 9.98,
    "klines": [
      "2022-12-15,9.93,10.17,10.20,9.93,38877,39386980.00,2.71,1.90,0.19,1.28"
    ]
  }
}
```

`klines` 字段顺序：

```text
日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
```

解析要点：

- `preKPrice` 是返回区间第一根 K 线的昨收；
- 第二根以后用上一根收盘价作为昨收；
- `secid` 前缀：沪市常用 `1.`，深市常用 `0.`；
- 普通 A 股涨停价可先按昨收 * 1.10 四舍五入到 2 位；ST/创业板/科创板/北交所需单独扩展。

## 东方财富请求失败模式

在一次实践中：

- 普通 Chrome 浏览器可打开 JSON；
- Python `requests` 返回 `RemoteDisconnected`；
- `curl_cffi` + `impersonate="chrome120"` 返回 `Connection closed abruptly`；
- 系统 `curl` 返回 `Empty reply from server`；
- Playwright 自动化 Chrome 返回 `net::ERR_EMPTY_RESPONSE`。

结论：浏览器可访问不代表 CLI/自动化可访问。不要因此索要东方财富账号密码；该历史 K 线 JSON 本身不是登录态问题。优先选择：

1. 本地 JSON 导入；
2. 连接用户已打开的普通浏览器 DevTools；
3. 换 Tushare 或其他数据源；
4. 让用户复制浏览器 DevTools 中的完整 request headers 排查，但不要收集 Cookie/账号密码，除非用户明确接受风险且是只读小号。

## Tushare 接入注意事项

依赖：

```bash
.venv/bin/python -m pip install tushare python-dotenv
```

`.env`：

```text
TUSHARE_TOKEN=...
```

`.gitignore` 必须包含：

```text
.env
```

代码转换：

```python
def normalize_ts_code(code: str) -> str:
    if "." in code:
        return code.upper()
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"
```

Tushare `daily` 返回的 `amount` 单位是千元，项目内部如果用元，应乘以 1000。

常见权限问题：

```text
抱歉，您没有接口(daily)访问权限
抱歉，您没有接口(stock_basic)访问权限
```

token 能被读取不等于账号有接口权限。必须实际调用 `stock_basic` 和 `daily` 验证。

## 策略案例检查经验

用户给出的案例可能描述的是某一天“周四/买点/正面教材”，不一定是 D2 日期。写 `case_check` 时要允许显式指定日期含义，避免把“案例日期”误解释为 D2。

示例：佳力图 `603912` 被用户称为 `2022-12-29 周四` 正面教材，不应自动等同于 `2022-12-21` 的 D2。
