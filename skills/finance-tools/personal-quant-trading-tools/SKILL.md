---
name: personal-quant-trading-tools
description: "构建个人量化/选股助手：策略规则化、行情数据源接入、回测、盘中提醒与复盘。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [quant, stocks, trading-tools, backtest, data-provider, alerts]
    category: finance-tools
---

# Personal Quant Trading Tools 个人量化/选股助手

## 屠龙 D3/D4 规则迁移说明

屠龙 D3/D4 监控规则的主版本已迁移到 `stock-strategy-assistant`：`references/tulong-d3-d4-monitoring.md`。后续新增或修正 D3 候选区、D4 强势雷达、盘中提醒频率、提醒格式和监控池替换规则时，以 `stock-strategy-assistant` 为唯一主版本；本文件仅保留历史参考，不再作为维护入口。

## 场景

当用户要构建、调试或迭代个人使用的选股/量化/行情监控工具时使用本 skill，尤其包括：

- A 股/港股/美股选股助手；
- 中短线策略规则化、回测和日报；
- 屠龙战术、首板、波段、突破/回踩/反包等交易规则转代码；
- 东方财富、AkShare、Tushare、CSV/JSON 本地行情导入；
- 盘中提醒、止损/止盈/失效条件、交易复盘周报。

## 重要边界

1. **不要给个性化投资指令**：输出策略信号、候选池、风险位、失效条件、回测结果和提醒，不输出“必买/必卖/保证收益”。
2. **先把策略规则化再谈实时**：把自然语言交易法拆成 D1/D2/D3 状态机、硬条件、排除条件、失效条件，再实现数据源和提醒。
3. **真实数据源必须验证权限与网络**：能安装库不代表接口可用；接口可用不代表账号有权限。
4. **凭证最小化**：不要索要交易账号密码、短信验证码、交易密码、完整 Cookie。API token 写入本地 `.env` 并加入 `.gitignore`。
5. **回测先行**：盘中提醒前，至少用历史样本验证正反案例，避免把未经验证的交易法做成实时噪声机器。

## 推荐项目结构

```text
a-share-stock-assistant/
├── config/
│   ├── strategy.yaml
│   ├── universe.yaml
│   └── alert.yaml
├── data/
│   ├── raw/
│   ├── processed/
│   └── watchlists/
├── reports/
│   ├── daily/
│   └── *.md
├── src/stock_assistant/
│   ├── models.py
│   ├── indicators.py
│   ├── strategy_tulong.py
│   ├── strategy_swing.py
│   ├── backtest.py
│   ├── scanner.py
│   ├── intraday_monitor.py
│   ├── journal.py
│   ├── data_provider.py
│   ├── eastmoney.py
│   ├── eastmoney_playwright.py
│   └── tushare_provider.py
├── backtests/
└── tests/
```

## 实施流程

### 1. 规则化策略

把口头策略拆成状态机：

```text
D1 候选发现 → D2 确认/排除 → D3 观察/触发 → D4/D5 退出管理
```

每个状态至少写清：

- 必须满足条件；
- 强排除条件；
- 触发价/观察价；
- 失效价；
- 到期处理；
- 是否依赖分钟线，若 MVP 只有日线则写明近似方式。

### 2. 先建可测试骨架

优先实现：

- `DailyBar` / `StrategySignal` dataclass；
- 指标函数：MA、EXPMA、涨停判断、滚动高点；
- 策略函数：纯函数优先，便于测试；
- CSV provider：作为离线 fixture 和兜底；
- reporter/backtest/journal/alerting。

遵循 TDD：新策略/数据解析函数先写测试，再实现。

### 3. 数据源接入顺序

推荐顺序：

1. **CSV/本地 JSON**：最稳定，适合测试和正反例复现；
2. **Tushare**：稳定但依赖 token 权限；
3. **AkShare/东方财富公开接口**：方便但可能被网络、TLS 指纹、反爬影响；
4. **Playwright 浏览器抓取**：作为最后兜底，不要一开始就依赖。

### 4. 回测与案例检查

对策略至少输出：

- 交易数；
- 胜率；
- 平均收益；
- 最好/最差收益；
- 出场原因分布；
- 最近 N 笔交易明细。

对用户给出的正反案例，单独写 `case_check` 命令，验证策略能否区分。

### 5. 盘中提醒

只监控已进入观察池的股票，不要盘中全市场乱扫。提醒要包含：

- 当前价；
- 观察价/触发价；
- 失效价；
- 触发原因；
- 风险提示；
- 去重窗口。

### 6. 屠龙 D3 分层 + 限额 + 降噪

筛 D3 当日观察池时，先用 D1/D2 硬条件得到候选，再按质量分 A/B/C 层，避免把所有通过条件的票都放进高频提醒：

- A 强观察最多 2 只；
- B 轻观察最多 2 只；
- C 备选不进 5 分钟高频监控；
- 主监控总数默认不超过 4 只；
- 只提醒低吸观察区、回收观察价、接近/跌破失效位、强拉升不追高、冲高回落等结构事件，普通波动不刷屏。

更新观察池后必须验证盘中监控脚本实际读取了新的 `data/watchlists/tulong_d3.csv`，避免脚本硬编码旧股票再覆盖当天筛选结果。详细口径见 `references/tulong-d3-layered-monitoring.md`。

## A 股数据源注意事项

### 东方财富 JSON

公开 K 线接口返回 `klines`，字段通常为：

```text
日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
```

`preKPrice` 可作为第一根 K 线的昨收，后续昨收用上一根收盘价。

### Tushare

- token 放 `.env`：`TUSHARE_TOKEN=...`；
- `.env` 必须加入 `.gitignore`；
- A 股代码转换：`603912 -> 603912.SH`，`000001 -> 000001.SZ`；
- `daily.amount` 单位是千元，转项目内部金额时乘以 1000；
- token 可读取不代表有接口权限；需实际调用 `stock_basic` / `daily` 验证。

### 东方财富/自动化抓取的陷阱

浏览器能打开，不代表 Python/curl/Playwright 能打开。若遇到 `RemoteDisconnected`、`ERR_EMPTY_RESPONSE`：

1. 先确认浏览器直接 URL 是否返回 JSON；
2. 再尝试 requests、curl_cffi、系统 curl、Playwright；
3. 若 CLI/自动化均失败，优先做“本地 JSON 导入”或换数据源，不要执着索要账号密码；
4. 不要把账号密码、验证码、交易凭证作为行情接口解决方案。

详见 `references/a-share-data-provider-notes.md`。

## 验证命令模板

```bash
# 安装依赖
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[data,test]'

# 测试
.venv/bin/python -m pytest -q

# 收盘扫描
.venv/bin/python -m stock_assistant.scanner --provider csv --date 2024-01-03 --data-dir data/raw

# 案例检查
.venv/bin/python -m stock_assistant.case_check --case all --provider tushare

# 回测
PYTHONPATH=src .venv/bin/python backtests/tulong_backtest.py --provider csv --start 2024-01-01 --end 2024-01-06
```

## 常见错误

- 一开始就做实时提醒，策略和数据源都没验证；
- 没有把交易法拆成状态机，导致代码里混入模糊判断；
- 用“水下”“主力拉升前位置”等词但没有定义机器近似；
- 忽略成交量单位差异，如 Tushare `amount` 是千元；
- 把数据源网络问题误判为账号登录问题；
- 把交易提醒写成投资建议；
- 忘记把 `.env` 加入 `.gitignore`。
