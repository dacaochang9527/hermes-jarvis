# China Futures Public Data

This reference documents public data endpoints verified for PVC2609 futures analysis.

## PVC2609 Symbol Mapping

| Context | Symbol |
|---|---|
| Sina quote snapshot | `nf_V2609` |
| Sina K-line APIs | `V2609` |
| Contract label | `PVC2609` |

## Quote Snapshot

Endpoint:

```text
https://hq.sinajs.cn/list=nf_V2609
```

Request requirements:

- Use `Referer: https://finance.sina.com.cn`
- Decode response as `gbk`

Known fields observed from PVC2609:

| Index | Meaning observed | Example from 2026-06-18 snapshot |
|---:|---|---|
| 0 | contract name | `PVC2609` |
| 1 | time as HHMMSS | `150324` |
| 2 | open | `4638.000` |
| 3 | high | `4641.000` |
| 4 | low | `4580.000` |
| 5 | latest / close | `4616.000` |
| 6 | bid1 | `4615.000` |
| 7 | ask1 | `4616.000` |
| 8 | latest-like field | `4616.000` |
| 9 | settlement / average-like field | `4617.000` |
| 10 | previous settlement | `4654.000` |
| 11 | bid1 volume | `1` |
| 12 | ask1 volume | `59` |
| 13 | open interest | `1256297.000` |
| 14 | volume | `866347` |
| 15 | exchange short label | `连` |
| 16 | variety | `PVC` |
| 17 | date | `2026-06-18` |

Parsing note: combine field 17 date with field 1 HHMMSS to form the quote timestamp. Do not read the final trailing numeric fields as date/time.

Live-session compatibility note: Sina can return `field[5] == 0.000` while bid1/ask1 in fields 6/7 are valid, especially near session start. In monitor scripts, do not treat `field[5] <= 0` as a tradable last price. Fall back to the midpoint of valid bid1/ask1, or the single valid side if only one side is present; if no positive bid/ask exists, reject the quote and suppress trading/event output.

Limitations:

- This is one-level盘口 only, not five-level盘口.
- During non-trading periods it may return the latest completed trading day, not live data.
- It does not provide tick-by-tick active buy/sell or big-order classification.

## Minute K-lines

Endpoint pattern:

```text
https://stock2.finance.sina.com.cn/futures/api/json.php/InnerFuturesNewService.getFewMinLine?symbol=V2609&type=<N>
```

Supported types verified:

| Type | Status | Fields |
|---:|---|---|
| 3 | available | `d,o,h,l,c,v,p` |
| 15 | available | `d,o,h,l,c,v,p` |
| 30 | available | `d,o,h,l,c,v,p` |
| 60 | available | `d,o,h,l,c,v,p` |
| 120 | available | `d,o,h,l,c,v,p` |

Field meanings:

| Field | Meaning |
|---|---|
| `d` | timestamp |
| `o` | open |
| `h` | high |
| `l` | low |
| `c` | close |
| `v` | volume for the bar |
| `p` | open interest after / at the bar |

Use `p` differences between adjacent bars to infer open-interest increase/decrease. Do not label the change as 多开、空开、多平、空平 unless tick/order-flow data confirms it.

## Daily K-line

Endpoint:

```text
https://stock2.finance.sina.com.cn/futures/api/json.php/InnerFuturesNewService.getDailyKLine?symbol=V2609
```

Fields observed:

| Field | Meaning |
|---|---|
| `d` | date |
| `o` | open |
| `h` | high |
| `l` | low |
| `c` | close |
| `v` | daily volume |
| `p` | daily open interest |
| `s` | settlement / average-like field |

## Minimum Data Checklist For Analysis

Before a futures analysis or Markdown report, try to fetch:

- Quote snapshot: latest price, bid1/ask1, bid/ask size, volume, open interest, timestamp.
- 3m K-line: execution timing and micro trigger.
- 15m K-line: short-term structure.
- 30m K-line: morning/afternoon rhythm.
- 60m K-line: intraday directional bias.
- 120m K-line: larger intraday pressure/support.
- Daily K-line: trend, major support/resistance, MA/MACD/RSI.

If tick data is unavailable, say so explicitly.

## What Can Be Automated Now

With the public endpoints above, Hermes can:

1. Refresh one-level quote snapshot.
2. Fetch 3m/15m/30m/60m/120m/daily K-lines.
3. Compute MA, MACD, RSI, ATR-like range, recent highs/lows.
4. Compute volume changes and open-interest deltas.
5. Evaluate whether key levels are held, broken, reclaimed, or rejected.
6. Generate conditional long/short scenarios and save Markdown reports.

## What Requires Additional Data

The following require a trading terminal screenshot, paid/credentialed market data source, or another verified API:

- Five-level order book.
- Tick-by-tick trades.
- Active buy / active sell classification.
- Big-order alerts.
- Direct 多开、空开、多平、空平 labels.

When these are missing, approximate using price action + volume + open-interest deltas, but label the result as inference.
