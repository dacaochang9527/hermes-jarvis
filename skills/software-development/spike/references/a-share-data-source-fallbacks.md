# 数据源降级与案例验证记录：A 股历史日线

## 背景

一次 A 股选股助手项目中，需要为「屠龙战术」验证正反案例：

- 正面：佳力图 `603912`，D2 日期 `2022-12-29`
- 反面：天安新材 `603725`，D2 日期 `2023-07-28`

目标是获取 A 股历史日线，转成统一 `DailyBar`，再运行策略检查。

## 有效路径

### 1. 优先探测多个免费源，而不是卡死在单一接口

东方财富接口浏览器可访问，但 CLI/Python/自动化链路多次失败时，不要继续围绕账号登录或 Cookie 纠缠。直接探测 AkShare 的其他后端：

```python
import akshare as ak

# 新浪日线源：本次可用，字段完整，适合日线策略
ak.stock_zh_a_daily(symbol="sh603912", start_date="20221215", end_date="20221221", adjust="")

# 腾讯历史源：本次可用，但字段较少
ak.stock_zh_a_hist_tx(symbol="sh603912", start_date="20221215", end_date="20221221", adjust="")
```

本次可用的是 `ak.stock_zh_a_daily`。

### 2. AkShare 新浪日线字段

示例字段：

```text
date, open, high, low, close, volume, amount, outstanding_share, turnover
```

注意：

- `volume` 是股数；
- `amount` 是元；
- `turnover` 是小数形式，转百分比时乘以 100；
- 第一根 K 线的 `prev_close` 应该多取前若干天数据，用目标开始日前最后一个交易日 `close` 补上。

### 3. 股票代码转换

```python
def akshare_symbol_for_code(code: str) -> str:
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{prefix}{code}"
```

### 4. 东方财富接口排查结论

同一 URL 用户普通 Chrome 可访问 JSON，但以下自动化/CLI 方式失败：

- Python `requests`
- `curl_cffi` + `impersonate="chrome120"`
- 系统 `curl`
- Playwright 启动的自动化 Chrome

这类情况不要记录成“东方财富不可用”的硬规则；更稳妥的技能结论是：

> 浏览器可访问而 CLI/自动化失败时，先保留 JSON 解析器，但切换到其他数据源或本地 JSON 导入，避免在登录态和 Cookie 上消耗过多时间。

### 5. Tushare 权限坑

Tushare token 可读取不代表有日线权限。本次 token 对以下接口无权限：

- `stock_basic`
- `daily`

遇到类似报错时，不要继续调参数；应明确向用户说明需要开通对应接口，或切换数据源。

## 验证结果

用 AkShare 新浪日线源跑案例：

```bash
.venv/bin/python -m stock_assistant.case_check --case all --provider akshare-sina
```

得到：

```text
佳力图 603912：is_d1=True, is_d2=True, D2/D1 量比 1.41，生成 D3 观察信号
天安新材 603725：is_d1=True, is_d2=False, D2/D1 量比 5.28，超过 2 倍，被排除
```

这与用户提供的正反教材方向一致。

## 可复用实施要点

- 为每个数据源写 Provider，不要把接口细节写进策略模块。
- 统一输出 `DailyBar`，策略只依赖统一模型。
- 数据源接入要有小样本解析测试，不要只靠真实网络请求。
- 真实案例验证命令应能指定 provider，例如：

```bash
python -m stock_assistant.case_check --case all --provider akshare-sina
```
