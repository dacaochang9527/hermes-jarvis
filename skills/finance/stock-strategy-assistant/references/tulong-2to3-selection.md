# 屠龙二进三观察池筛选

## 适用场景

当用户要求“二进三”“2进3”“二连板晋级”等股票列表时，按独立连板晋级观察池处理，不混入 D3 首板低吸战法，也不要覆盖当前 `MMDDD3` 监控池，除非用户明确要求切池。

## 口径

- 数据日通常为目标交易日前一交易日，例如生成 `0623` 二进三时读取 `20260622` 涨停池。
- 只保留沪深主板 10cm：`000/001/002/003/600/601/603/605`。
- 过滤 ST、*ST、退市风险和 20cm/北交所。
- 核心条件：当日 `连板数 == 2`，作为次日二进三候选。
- 输出分层使用 `active` / `radar`，并在 `tag` 中明确写入“二进三”，避免和 D3 混淆。

## 推荐数据源

优先使用东方财富涨停池公开接口，避免在临时扫描中依赖较重的 akshare 封装：

```text
https://push2ex.eastmoney.com/getTopicZTPool
```

关键参数：

```text
ut=7eea3edcaed734bea9cbfc24409ed989
dpt=wz.ztzt
Pageindex=0
pagesize=200
sort=fbt:asc
date=YYYYMMDD
```

关键字段映射：

```text
c -> code
n -> name
p / 1000 -> price
zdp -> pct
amount / 1e8 -> amount_yi
hs -> turnover
fund / 1e8 -> seal_fund_yi
fbt -> first_seal
lbt -> last_seal
zbc -> breaks
lbc -> limit_boards
hybk -> industry
zttj.ct/zttj.days -> stat
```

## 分层评分建议

基础分 70：

- 首次封板：`<=09:30` +12，`<=10:00` +8，`<=11:00` +4，之后 -8。
- 炸板：0 次 +8，1 次 +2，多次 -8；炸板很多的票即使人气强也优先 radar。
- 封板资金：`>=3亿` +10，`>=1亿` +6，`>=0.3亿` +2，否则 -6。
- 换手：2%–15% +5；18%–25% -5；25% 以上 -10。
- 成交额：1–15 亿 +3；15–30 亿 -6；30 亿以上 -12；1 亿以下 -4。

默认 `score >= 82` 且成交额不拥挤、换手不过热才进入 `active`；否则进入 `radar`。active 建议控制在 4–6 只，radar 可保留 8–12 只。

## 输出文件

建议落盘：

```text
data/watchlists/MMDD_2to3_watch_scan_YYYYMMDD_HHMMSS.csv
reports/daily/MMDD_2to3_candidate_scan_YYYYMMDD_HHMMSS.md
```

CSV 字段至少包含：

```text
tag, code, name, industry, pool_subtype, score, rank, price, pct,
amount_yi, turnover, seal_fund_yi, first_seal, last_seal, breaks,
stat, limit_boards, trigger_price, zone_low, zone_high, invalid_price, note
```

## 盘后复盘并入日复盘

当用户在日复盘中说“把二进三也加进来 / 二进三那几只也加进来”时：

1. 先定位当日最新 `MMDD_2to3_watch_scan_YYYYMMDD_HHMMSS.csv` 和对应报告，不重新定义为 D3，也不覆盖 `MMDDD3` 观察池。
2. 将二进三作为独立章节并入当日复盘，标题明确写“二进三观察池复盘（独立，不计入 D3）”。
3. 交易归因中，若成交标的属于二进三池但不属于 D3 active，应归为“二进三观察交易 / HOLD”，不能反向计入 D3 active 成败。
4. 统计 active/radar 各自的红盘、涨停/近涨停、弱势数量和平均涨跌幅；同时列出高成交额、高价、冲高回落等接力风险。
5. 若本地盘中 snapshots 缺失，可用新浪批量 quote 拉取当日开高低收、昨收、成交额和涨跌幅，生成临时行情快照供复盘引用；这只是行情补齐路径，不改变二进三源文件。

## 注意事项

- 二进三是高波动接力观察池，报告中要明确“不是 D3 首板低吸战法”。
- 不要自动切入正式监控池；用户只说“筛一批”时只生成报告和 CSV。
- 对高价、成交额拥挤、炸板次数多的票，即使连板强度高也要降为 radar 或在 note 中突出风险。
- 如果 akshare 涨停池封装超时，可以直接用东方财富接口获取同源数据；记录的是“使用轻量接口兜底”的方法，不要固化为 akshare 不可用。