# 东方财富 A 股历史 K 线接口经验

本参考记录一次构建 A 股选股/回测工具时对东方财富历史 K 线接口的验证经验，供未来类似市场数据自动化任务复用。

## 接口形态

示例：

```text
https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=0&secid=1.603912&beg=20221215&end=20221221
```

关键参数：

- `secid=1.603912`：沪市前缀 `1.`；
- `secid=0.000001`：深市常用前缀 `0.`；
- `klt=101`：日 K；
- `fqt=0`：不复权；
- `beg/end`：`YYYYMMDD`。

## 返回 JSON 结构

典型结构：

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

`klines` 字段格式：

```text
日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
```

解析要点：

- 第一根 K 线的昨收可用 `preKPrice`；
- 后续 K 线昨收使用上一交易日收盘；
- 普通 A 股涨停价可先按昨收 × 1.10 粗算；
- ST、创业板、科创板、北交所涨跌停制度需后续区分；
- 如果做分钟级策略，“拉升前位置”不能只靠日线精确判断。

## 凭证安全结论

用户东方财富账号密码、短信验证码、交易密码、完整 Cookie 都不应要求提供。

历史 K 线接口通常是公开只读数据；当 Python 请求失败时，应先排查网络/请求特征/接口限制，而不是索要登录凭证。

## 请求失败排查路径

一次实际验证中出现：

- 浏览器手动打开 URL 能返回 JSON；
- Python `requests` 报 `RemoteDisconnected`；
- `curl_cffi` 报 `Connection closed abruptly`；
- 系统 `curl` 报 `Empty reply from server`；
- Playwright 自动化 Chrome 报 `ERR_EMPTY_RESPONSE`。

处理建议：

1. 保留本地 JSON/CSV 导入路径，不让网络问题阻塞策略验证；
2. 如浏览器可访问，可让用户保存 JSON 文件再解析；
3. 如必须自动化，可尝试连接用户正在使用的普通 Chrome DevTools，而不是启动自动化浏览器；
4. 更稳的长期方案是接 Tushare/BaoStock 等备用数据源。

## 可复用实现要点

建议实现：

```python
def market_id_for_code(code: str) -> int:
    return 1 if code.startswith(("5", "6", "9")) else 0


def bars_from_eastmoney_json(payload: dict) -> list[DailyBar]:
    ...
```

并搭配：

- `CsvDailyDataProvider` / `JsonDailyDataProvider`；
- `EastmoneyDirectProvider`；
- `EastmoneyPlaywrightProvider`；
- 单元测试使用用户提供的 JSON fixture，不依赖网络。
