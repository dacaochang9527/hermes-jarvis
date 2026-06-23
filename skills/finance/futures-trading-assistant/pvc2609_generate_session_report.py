#!/usr/bin/env python3
"""Generate PVC2609 day/night review + next-session plan Markdown drafts.

The generator fetches public Sina quote/K-line data, reads local monitor logs,
and writes a structured report skeleton matching the futures session-state chain.
It is intentionally conservative: generated conclusions are marked as drafts and
should be reviewed before publishing or trading from them.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
RUNTIME_DIR = BASE_DIR / "runtime" / "pvc2609_feishu_monitor"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
BRIEFING_LOG = RUNTIME_DIR / "half_hour_briefings.jsonl"
PREDICTION_LEVELS_PATH = RUNTIME_DIR / "latest_prediction_levels.json"
QUOTE_URL = "https://hq.sinajs.cn/list=nf_V2609"
KLINE_URL = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_{minutes}=/InnerFuturesNewService.getFewMinLine?symbol=V2609&type={minutes}"
DAILY_URL = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_D=/InnerFuturesNewService.getDailyKLine?symbol=V2609"
CONTRACT = "PVC2609"
SYMBOL = "V2609"
TZ = ZoneInfo("Asia/Shanghai")
MINUTE_PERIODS = (3, 15, 30, 60, 120)

SESSION_WINDOWS = {
    "day": [(time(9, 0), time(10, 15)), (time(10, 30), time(11, 30)), (time(13, 30), time(15, 0))],
    "night": [(time(21, 0), time(23, 0))],
}


@dataclass
class Bar:
    dt: datetime | None
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float


def now_cn() -> datetime:
    return datetime.now(TZ)


def fetch_text(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("gbk", errors="replace")


def to_float(value: object, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, (int, float, str)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return default


def parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    text = str(raw)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def parse_quote(raw: str) -> dict:
    match = re.search(r'="([^"]*)"', raw)
    if not match:
        raise ValueError(f"unexpected quote response: {raw[:120]}")
    fields = match.group(1).split(",")
    if len(fields) < 18:
        raise ValueError(f"quote has too few fields: {fields}")
    time_raw = fields[1]
    raw_last = to_float(fields[5])
    bid = to_float(fields[6])
    ask = to_float(fields[7])
    last = raw_last
    if math.isnan(last) or last <= 0:
        valid_quotes = [value for value in (bid, ask) if not math.isnan(value) and value > 0]
        if len(valid_quotes) == 2:
            last = sum(valid_quotes) / 2
        elif valid_quotes:
            last = valid_quotes[0]
    if math.isnan(last) or last <= 0:
        raise ValueError("quote last price unavailable")
    time_str = f"{time_raw[:2]}:{time_raw[2:4]}:{time_raw[4:6]}" if len(time_raw) == 6 else "00:00:00"
    quote_dt = datetime.strptime(f"{fields[17]} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    return {
        "name": fields[0] or CONTRACT,
        "open": to_float(fields[2]),
        "high": to_float(fields[3]),
        "low": to_float(fields[4]),
        "last": last,
        "bid": bid,
        "ask": ask,
        "open_interest": to_float(fields[13]),
        "volume": to_float(fields[14]),
        "quote_dt": quote_dt,
        "raw": fields,
    }


def parse_jsonp_array(raw: str) -> list:
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end < start:
        return []
    return json.loads(raw[start:end + 1])


def fetch_klines(minutes: int) -> list[Bar]:
    data = parse_jsonp_array(fetch_text(KLINE_URL.format(minutes=minutes)))
    rows: list[Bar] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        open_ = to_float(item.get("o"))
        high = to_float(item.get("h"))
        low = to_float(item.get("l"))
        close = to_float(item.get("c"))
        if any(math.isnan(value) for value in (open_, high, low, close)):
            continue
        rows.append(Bar(parse_dt(item.get("d") or item.get("date") or item.get("datetime")), open_, high, low, close, to_float(item.get("v"), 0.0), to_float(item.get("p"), 0.0)))
    return rows


def fetch_daily() -> list[Bar]:
    data = parse_jsonp_array(fetch_text(DAILY_URL))
    rows: list[Bar] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        open_ = to_float(item.get("o"))
        high = to_float(item.get("h"))
        low = to_float(item.get("l"))
        close = to_float(item.get("c"))
        if any(math.isnan(value) for value in (open_, high, low, close)):
            continue
        rows.append(Bar(parse_dt(item.get("d")), open_, high, low, close, to_float(item.get("v"), 0.0), to_float(item.get("p"), 0.0)))
    return rows


def bars_for_session(rows: list[Bar], trading_date: date, session: str) -> list[Bar]:
    windows = SESSION_WINDOWS[session]
    filtered = []
    for row in rows:
        if row.dt is None or row.dt.date() != trading_date:
            continue
        current = row.dt.time()
        if any(start <= current <= end for start, end in windows):
            filtered.append(row)
    return filtered


def summarize_bars(rows: list[Bar]) -> dict:
    if not rows:
        return {"open": math.nan, "high": math.nan, "low": math.nan, "close": math.nan, "volume": 0.0, "oi_start": math.nan, "oi_end": math.nan, "oi_delta": math.nan, "start": None, "end": None}
    return {
        "open": rows[0].open,
        "high": max(row.high for row in rows),
        "low": min(row.low for row in rows),
        "close": rows[-1].close,
        "volume": sum(row.volume for row in rows),
        "oi_start": rows[0].open_interest,
        "oi_end": rows[-1].open_interest,
        "oi_delta": rows[-1].open_interest - rows[0].open_interest,
        "start": rows[0].dt,
        "end": rows[-1].dt,
    }


def moving_average(rows: list[Bar], length: int) -> float:
    if len(rows) < length:
        return math.nan
    return sum(row.close for row in rows[-length:]) / length


def rsi(rows: list[Bar], length: int = 14) -> float:
    if len(rows) <= length:
        return math.nan
    gains = []
    losses = []
    recent = rows[-(length + 1):]
    for prev, curr in zip(recent, recent[1:]):
        change = curr.close - prev.close
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def trend_label(rows: list[Bar]) -> str:
    if len(rows) < 6:
        return "数据不足"
    recent = rows[-6:]
    move = recent[-1].close - recent[0].close
    high_break = recent[-1].high >= max(row.high for row in recent[:-1])
    low_break = recent[-1].low <= min(row.low for row in recent[:-1])
    if move > 12 and high_break:
        return "偏强修复/上行"
    if move < -12 and low_break:
        return "偏弱下行"
    if abs(move) <= 12:
        return "震荡整理"
    return "缓慢修复" if move > 0 else "缓慢转弱"


def fmt_price(value: float) -> str:
    if value is None or math.isnan(value):
        return "N/A"
    return f"{value:.0f}"


def fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def read_jsonl(path: Path, trading_date: date, session: str, limit: int = 8) -> list[dict]:
    if not path.exists():
        return []
    windows = SESSION_WINDOWS[session]
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        stamp = None
        for key in ("quote_dt", "created_at", "alert_at", "now", "ts", "timestamp"):
            stamp = parse_dt(record.get(key))
            if stamp:
                break
        if stamp is None or stamp.date() != trading_date:
            continue
        if any(start <= stamp.time() <= end for start, end in windows):
            records.append(record)
    return records[-limit:]


def find_prior_report(trading_date: date, session: str) -> Path | None:
    if session == "night":
        candidates = [REPORTS_DIR / f"pvc2609_{trading_date:%Y%m%d}_day_review_night_plan.md"]
    else:
        previous = trading_date - timedelta(days=1)
        candidates = [
            REPORTS_DIR / f"pvc2609_{previous:%Y%m%d}_night_review_next_day_plan.md",
            REPORTS_DIR / f"pvc2609_{trading_date:%Y%m%d}_night_review_next_day_plan.md",
        ]
    for path in candidates:
        if path.exists():
            return path
    return None


def extract_handoff(path: Path | None) -> str:
    if path is None or not path.exists():
        return "未找到前序 STATE_HANDOFF，请人工补充前序计划验证。"
    text = path.read_text(encoding="utf-8")
    idx = text.rfind("STATE_HANDOFF")
    if idx < 0:
        return "前序文档未找到 STATE_HANDOFF，请人工补充前序计划验证。"
    return text[idx:].strip("`\n ")[:1800]


def derive_levels(summary: dict, quote: dict, rows_15m: list[Bar]) -> dict:
    session_low = summary["low"] if not math.isnan(summary["low"]) else quote["low"]
    session_high = summary["high"] if not math.isnan(summary["high"]) else quote["high"]
    close = summary["close"] if not math.isnan(summary["close"]) else quote["last"]
    recent = rows_15m[-32:] if len(rows_15m) >= 8 else rows_15m
    if recent:
        lows = sorted(row.low for row in recent)
        highs = sorted(row.high for row in recent)
        support = lows[max(0, int(len(lows) * 0.25) - 1)]
        resistance = highs[min(len(highs) - 1, int(len(highs) * 0.75))]
    else:
        support = session_low
        resistance = session_high
    if support >= close:
        support = min(session_low, close - 8)
    if resistance <= close:
        resistance = max(session_high, close + 8)
    return {
        "close": close,
        "session_low": session_low,
        "session_high": session_high,
        "support": support,
        "resistance": resistance,
        "upper_confirm": resistance + 12,
        "lower_confirm": support - 12,
    }


def infer_bias(summary: dict, daily: list[Bar]) -> str:
    close = summary["close"]
    open_ = summary["open"]
    ma5 = moving_average(daily, 5)
    if math.isnan(close) or math.isnan(open_):
        return "range"
    if not math.isnan(ma5) and close < ma5 and close > open_:
        return "range_repair"
    if not math.isnan(ma5) and close < ma5 and close <= open_:
        return "bearish"
    if close > open_:
        return "repair"
    return "range"


def build_report(args: argparse.Namespace, quote: dict, klines: dict[int, list[Bar]], daily: list[Bar], prior_report: Path | None) -> tuple[str, dict]:
    session_rows_3m = bars_for_session(klines.get(3, []), args.date, args.session)
    session_summary = summarize_bars(session_rows_3m or klines.get(3, [])[-80:])
    levels = derive_levels(session_summary, quote, klines.get(15, []))
    bias = infer_bias(session_summary, daily)
    next_session = "night" if args.session == "day" else "next_day_day"
    report_name = default_report_name(args.date, args.session)
    source_doc = f"reports/{report_name}"
    generated_at = now_cn()
    quote_stale = "是" if quote["quote_dt"].date() != args.date else "否"
    ma5 = moving_average(daily, 5)
    ma10 = moving_average(daily, 10)
    ma20 = moving_average(daily, 20)
    daily_rsi = rsi(daily)
    prior_handoff = extract_handoff(prior_report)
    event_records = read_jsonl(EVENT_LOG, args.date, args.session)
    briefing_records = read_jsonl(BRIEFING_LOG, args.date, args.session)
    monitor_note = f"事件日志 {len(event_records)} 条样本；半小时简报 {len(briefing_records)} 条样本（本报告仅列最近样本）。"

    timeframe_rows = []
    if daily:
        latest_daily = daily[-1]
        timeframe_rows.append(["日K", "大周期趋势背景", f"高 {fmt_price(latest_daily.high)} / 低 {fmt_price(latest_daily.low)} / 收 {fmt_price(latest_daily.close)}", f"MA5/10/20={fmt_price(ma5)}/{fmt_price(ma10)}/{fmt_price(ma20)}，RSI={daily_rsi:.1f}" if not math.isnan(daily_rsi) else f"MA5/10/20={fmt_price(ma5)}/{fmt_price(ma10)}/{fmt_price(ma20)}", "先定大背景，不用小周期单根K线推翻。"])
    for minutes in (120, 60, 30, 15, 3):
        rows = klines.get(minutes, [])
        summary = summarize_bars(bars_for_session(rows, args.date, args.session) or rows[-12:])
        timeframe_rows.append([f"{minutes}m", trend_label(rows), f"区间 {fmt_price(summary['low'])}-{fmt_price(summary['high'])} / 收 {fmt_price(summary['close'])}", f"量 {summary['volume']:.0f}，持仓变化 {fmt_price(summary['oi_delta'])}", "用于确认边界突破、跌破、回收或承压。"])
    timeframe_md = "\n".join(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |" for row in timeframe_rows)

    event_md = "\n".join(format_monitor_record(record) for record in event_records) or "| 暂无 | 暂无 | 暂无 | 暂无 |"
    briefing_md = "\n".join(format_monitor_record(record) for record in briefing_records) or "| 暂无 | 暂无 | 暂无 | 暂无 |"

    title_date = args.date.strftime("%Y-%m-%d")
    next_title = "夜盘" if args.session == "day" else "次日日盘"
    completed_title = "日盘" if args.session == "day" else "夜盘"
    filename_date = args.date.strftime("%Y%m%d")
    next_date_text = args.date.strftime("%Y-%m-%d") if args.session == "day" else (args.date + timedelta(days=1)).strftime("%Y-%m-%d")

    markdown = f"""# PVC2609 {title_date} {completed_title}复盘 + {next_date_text} {next_title}计划

> 生成时间：{generated_at.strftime('%Y-%m-%d %H:%M CST')}  
> 生成方式：`pvc2609_generate_session_report.py` 自动骨架，需人工复核后作为正式交易文档  
> 标的：PVC2609 期货合约  
> 复盘对象：{title_date} {completed_title}  
> 前序计划：`{prior_report.relative_to(BASE_DIR) if prior_report else '未找到'}`  
> 数据源：新浪期货公开 quote、3m/15m/30m/60m/120m K线、日K、本地事件监控、本地30分钟简报  
> 数据状态：quote 返回 `{fmt_dt(quote['quote_dt'])}`，当前/收盘参考 `{fmt_price(quote['last'])}`，quote 日期与复盘日期不一致：{quote_stale}  
> 数据限制：公开行情只有一档盘口，不能还原逐笔主动买卖；K线量仓只用于结构参考，不能直接标注多开/空开/多平/空平。  
> 风险提示：本文为交易复盘与条件化计划，不构成确定性投资建议；期货杠杆高，必须先设止损。

## 1. 一句话结论（自动草稿）

{completed_title}区间 `{fmt_price(session_summary['low'])}-{fmt_price(session_summary['high'])}`，收盘/最新参考 `{fmt_price(session_summary['close'])}`；当前自动判断为 `{bias}`。下一阶段优先围绕 `{fmt_price(levels['support'])}` 支撑、`{fmt_price(levels['resistance'])}` 压力、`{fmt_price(levels['upper_confirm'])}` 上方确认位和 `{fmt_price(levels['lower_confirm'])}` 下方确认位做条件化验证。请人工复核是否存在假破、回收、承压或趋势延续。

## 2. 数据状态与行情摘要

| 项目 | 数值 |
|---|---:|
| quote 时间 | {fmt_dt(quote['quote_dt'])} |
| quote 最新/收盘参考 | {fmt_price(quote['last'])} |
| quote 日内最高 | {fmt_price(quote['high'])} |
| quote 日内最低 | {fmt_price(quote['low'])} |
| {completed_title}K线开盘参考 | {fmt_price(session_summary['open'])} |
| {completed_title}K线最高 | {fmt_price(session_summary['high'])} |
| {completed_title}K线最低 | {fmt_price(session_summary['low'])} |
| {completed_title}K线收盘参考 | {fmt_price(session_summary['close'])} |
| {completed_title}成交量合计 | {session_summary['volume']:.0f} |
| {completed_title}持仓变化 | {fmt_price(session_summary['oi_delta'])} |
| 本地监控样本 | {monitor_note} |

## 3. 前序 STATE_HANDOFF 摘要

```text
{prior_handoff}
```

## 4. 多周期结构总表

| 周期 | 方向/结构 | 关键位 | 指标/量仓状态 | 交易含义 |
|---|---|---|---|---|
{timeframe_md}

## 5. 前序计划逐项验证（需人工补充）

| 前序方案 | 计划触发 | 实际路径 | 匹配状态 | 原因 | 执行含义 |
|---|---|---|---|---|---|
| 方案 A | 从前序计划补充 | 本次区间 {fmt_price(session_summary['low'])}-{fmt_price(session_summary['high'])} | 待复核 | 根据触发、回收、承压、量仓变化判断 | 不只看方向对错，要看触发质量 |
| 方案 B | 从前序计划补充 | 本次收盘/最新 {fmt_price(session_summary['close'])} | 待复核 | 根据关键位是否有效跌破/站回判断 | 未触发也要记录，避免 hindsight bias |
| 方案 C | 从前序计划补充 | 参考本地监控与K线节奏 | 待复核 | 公共数据无逐笔主动买卖 | 执行评价需与市场匹配度分开 |

## 6. 时间维度预测 vs 实际验证（需人工补充）

| 复盘维度 | 前序预测/计划 | 实际走势 | 相符度 | 偏差来源 | 下次修正 |
|---|---|---|---|---|---|
| 开盘 | 待补充 | 开盘参考 {fmt_price(session_summary['open'])} | 待复核 | 待补充 | 开盘首段优先观察 |
| 前30分钟 | 待补充 | 结合3m/15m走势复核 | 待复核 | 待补充 | 破位/突破需确认 |
| 主段 | 待补充 | 区间 {fmt_price(session_summary['low'])}-{fmt_price(session_summary['high'])} | 待复核 | 待补充 | 区分趋势延续与区间修复 |
| 尾盘/收盘 | 待补充 | 收盘参考 {fmt_price(session_summary['close'])} | 待复核 | 待补充 | 收盘位置决定下一阶段中轴 |
| 波动区间 | 待补充 | 实际区间 {fmt_price(session_summary['low'])}-{fmt_price(session_summary['high'])} | 待复核 | 待补充 | 保留假破/假突破判断 |

## 7. 命中/偏差归因与逻辑修正（自动骨架）

| 问题类型 | 本次表现 | 造成后果 | 后续规则 |
|---|---|---|---|
| 趋势惯性 | 自动判断 `{bias}`，需结合日K复核 | 可能把修复误当反转，或把趋势空执行得太机械 | 大周期定背景，小周期定入场 |
| 关键位确认 | 支撑 `{fmt_price(levels['support'])}`，压力 `{fmt_price(levels['resistance'])}` | 单次触碰不能代表有效突破/跌破 | 看3m/15m收盘、反抽不过或回踩不破 |
| 持仓解释 | 本阶段持仓变化 `{fmt_price(session_summary['oi_delta'])}` | 只能说明持仓增减，不能直接标注多开/空开 | 量仓结论必须写成推断而非逐笔事实 |
| 执行颗粒 | 中轴区间易反复 | 高频碎单可能被震荡消耗 | 只在边界和确认位做决策 |

## 8. 本地监控与盘面验证

事件监控最近样本：

| 时间 | 价格 | 事件/状态 | 备注 |
|---|---:|---|---|
{event_md}

半小时简报最近样本：

| 时间 | 价格 | 事件/状态 | 备注 |
|---|---:|---|---|
{briefing_md}

## 9. 关键位变化表（自动草稿）

| 点位 | 当前角色 | 验证方式 | 下一阶段含义 |
|---:|---|---|---|
| {fmt_price(levels['session_low'])} | 本阶段低点 | 跌破后能否收回 | 下方风险释放/假破观察 |
| {fmt_price(levels['support'])} | 近端支撑 | 3m/15m是否有效跌破 | 跌破且反抽不过才偏弱 |
| {fmt_price(levels['close'])} | 当前中轴 | 能否站稳/跌回 | 判断修复或转弱节奏 |
| {fmt_price(levels['resistance'])} | 近端压力 | 冲高是否承压 | 承压转弱才考虑反向 |
| {fmt_price(levels['upper_confirm'])} | 上方确认位 | 站稳/回踩不破 | 修复延续确认 |

## 10. {next_date_text} {next_title}情景概率表（自动草稿，需人工复核）

| 剧本 | 触发条件 | 预期路径 | 估计概率 | 关键证据 | 失效条件 |
|---|---|---|---:|---|---|
| A：压力位承压回落 | 反抽到 {fmt_price(levels['resistance'])}-{fmt_price(levels['upper_confirm'])} 后3m转弱 | 回看 {fmt_price(levels['close'])}，再看 {fmt_price(levels['support'])} | 30%-40% | 压力区未站稳 | 站稳 {fmt_price(levels['upper_confirm'])} |
| B：上方确认后的修复延续 | 站稳 {fmt_price(levels['upper_confirm'])} 且回踩不破 | 上看更高一级压力，人工补充 | 25%-35% | 修复/突破得到确认 | 跌回 {fmt_price(levels['resistance'])} 下方 |
| C：跌破支撑后的弱势延续 | 跌破 {fmt_price(levels['support'])} 且反抽不过 | 回看 {fmt_price(levels['lower_confirm'])} 附近 | 25%-35% | 支撑失守且未收回 | 快速收回 {fmt_price(levels['support'])} |
| D：中轴震荡无交易 | 价格在 {fmt_price(levels['support'])}-{fmt_price(levels['resistance'])} 内反复 | 观望 | — | 空间不足、触发不清 | 突破或跌破边界并确认 |

## 11. 操作计划（自动骨架）

### 方案 A：压力承压后的空

| 项目 | 计划 |
|---|---|
| 方向 | 反抽承压空 |
| 入场区 | {fmt_price(levels['resistance'])}-{fmt_price(levels['upper_confirm'])} 承压后，3m转弱再考虑 |
| 仓位 | 1手基础；确认后才考虑加仓 |
| 止损 | {fmt_price(levels['upper_confirm'] + 8)} 上方或重新站稳确认位 |
| 第一止盈 | {fmt_price(levels['close'])} |
| 第二止盈 | {fmt_price(levels['support'])} |
| 主要风险 | 若上方确认位站稳，继续空容易被修复延续挤压 |

### 方案 B：上方确认后的修复延续

| 项目 | 计划 |
|---|---|
| 方向 | 修复多/空头回补延续 |
| 入场区 | {fmt_price(levels['upper_confirm'])} 站稳回踩不破后再考虑 |
| 仓位 | 1手；趋势未确认前不加大仓位 |
| 止损 | 跌回 {fmt_price(levels['resistance'])} 下方 |
| 第一止盈 | 人工补充上方压力 |
| 主要风险 | 大周期若仍弱，修复多不能当趋势反转 |

### 方案 C：跌破支撑后的弱势延续

| 项目 | 计划 |
|---|---|
| 方向 | 支撑失守后的延续空 |
| 入场区 | 跌破 {fmt_price(levels['support'])} 后，反抽不过再考虑 |
| 仓位 | 1手；不追第一根急跌 |
| 止损 | 重新站回 {fmt_price(levels['support'])} 或 {fmt_price(levels['close'])} |
| 第一止盈 | {fmt_price(levels['lower_confirm'])} |
| 主要风险 | 低位假破后快速收回 |

## 12. 小资金点数现实与风险可行性

PVC期货每手5吨，价格每波动1点约5元/手。下面不是收益承诺，只用于判断目标是否现实。

| 目标盈亏 | 1手所需点数 | 2手所需点数 | 3手所需点数 | 当前行情可行性 | 建议姿态 |
|---|---:|---:|---:|---|---|
| 100元 | 20点 | 10点 | 约7点 | 边界触发后较现实 | 到位先保护 |
| 200元 | 40点 | 20点 | 约14点 | 需要从支撑/压力边界入场 | 不在中轴追单 |
| 300元 | 60点 | 30点 | 20点 | 需要完整波段配合 | 等确认，不碎单 |
| 500元 | 100点 | 50点 | 约34点 | 难度较高，易诱导重仓 | 不建议作为单日硬目标 |

## 13. 最终执行口径（自动草稿）

- `{fmt_price(levels['resistance'])}-{fmt_price(levels['upper_confirm'])}` 承压转弱：按反抽承压空观察。
- `{fmt_price(levels['upper_confirm'])}` 站稳：停止死空，按修复延续观察。
- `{fmt_price(levels['support'])}` 跌破且反抽不过：才按弱势延续处理。
- `{fmt_price(levels['support'])}-{fmt_price(levels['resistance'])}` 中轴反复：观望优先，避免碎单。

```text
STATE_HANDOFF
contract: PVC2609
source_doc: {source_doc}
session_completed: {args.session}
next_session: {next_session}
bias: {bias}
risk_flags: auto_generated, needs_human_review, one_level_quote_only, no_tick_active_flow
must_watch_levels:
  - price: {fmt_price(levels['support'])}
    role: support
    label: 近端支撑/跌破确认位
    trigger: break_down_or_reclaim
  - price: {fmt_price(levels['resistance'])}
    role: resistance
    label: 近端压力/承压观察位
    trigger: rejection_or_break_up
  - price: {fmt_price(levels['upper_confirm'])}
    role: repair_confirmation
    label: 修复延续确认位
    trigger: break_up_or_fail
  - price: {fmt_price(levels['lower_confirm'])}
    role: breakdown_target
    label: 下方延续观察位
    trigger: reach_or_reclaim
invalidated_levels:
  - price: TBD
    reason: 人工复核前序计划后补充
monitor_levels_updated: {str(args.update_levels).lower()}
```
"""

    prediction_payload = {
        "contract": CONTRACT,
        "source_doc": source_doc,
        "updated_at": generated_at.isoformat(),
        "session": next_session,
        "levels": [
            {"price": round(levels["support"]), "role": "support", "label": "近端支撑/跌破确认位", "direction": "both"},
            {"price": round(levels["resistance"]), "role": "resistance", "label": "近端压力/承压观察位", "direction": "both"},
            {"price": round(levels["upper_confirm"]), "role": "repair_confirmation", "label": "修复延续确认位", "direction": "up"},
            {"price": round(levels["lower_confirm"]), "role": "breakdown_target", "label": "下方延续观察位", "direction": "down"},
        ],
    }
    return markdown, prediction_payload


def format_monitor_record(record: dict) -> str:
    stamp = None
    for key in ("quote_dt", "created_at", "alert_at", "now", "ts", "timestamp"):
        stamp = parse_dt(record.get(key))
        if stamp:
            break
    price = record.get("price") or record.get("last") or record.get("quote_price") or record.get("current_price") or "N/A"
    event = record.get("event") or record.get("event_type") or record.get("status") or record.get("scenario") or record.get("title") or "状态记录"
    note = record.get("note") or record.get("reason") or record.get("message") or record.get("brief") or "本地日志样本"
    return f"| {fmt_dt(stamp)} | {price} | {event} | {str(note).replace('|', '/')} |"


def default_report_name(trading_date: date, session: str) -> str:
    if session == "day":
        return f"pvc2609_{trading_date:%Y%m%d}_day_review_night_plan.md"
    return f"pvc2609_{trading_date:%Y%m%d}_night_review_next_day_plan.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PVC2609 session report Markdown draft.")
    parser.add_argument("--date", required=True, type=lambda value: datetime.strptime(value, "%Y%m%d").date(), help="natural trading date, e.g. 20260623")
    parser.add_argument("--session", required=True, choices=("day", "night"), help="completed session to review")
    parser.add_argument("--output", type=Path, help="output markdown path; defaults to reports/<standard_name>")
    parser.add_argument("--overwrite", action="store_true", help="allow overwriting an existing report")
    parser.add_argument("--update-levels", action="store_true", help="write runtime latest_prediction_levels.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = args.output or (REPORTS_DIR / default_report_name(args.date, args.session))
    if output.exists() and not args.overwrite:
        draft = output.with_name(output.stem + f"_draft_{now_cn():%H%M%S}" + output.suffix)
        output = draft

    quote = parse_quote(fetch_text(QUOTE_URL))
    klines = {minutes: fetch_klines(minutes) for minutes in MINUTE_PERIODS}
    daily = fetch_daily()
    prior_report = find_prior_report(args.date, args.session)
    markdown, prediction_payload = build_report(args, quote, klines, daily, prior_report)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    if args.update_levels:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        PREDICTION_LEVELS_PATH.write_text(json.dumps(prediction_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(output))
    if args.update_levels:
        print(str(PREDICTION_LEVELS_PATH))
    return 0


if __name__ == "__main__":
    sys.exit(main())
