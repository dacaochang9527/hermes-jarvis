#!/usr/bin/env python3
"""PVC2609 event-driven monitor for Hermes cron.

Prints a Feishu-ready alert only when an event should be pushed.
Otherwise prints nothing so no_agent cron remains silent.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "configs" / "pvc2609_feishu_monitor.yaml"
RUNTIME_DIR = BASE_DIR / "runtime" / "pvc2609_feishu_monitor"
STATE_PATH = RUNTIME_DIR / "last_alert_state.json"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
QUOTE_URL = "https://hq.sinajs.cn/list=nf_V2609"
SYMBOL = "V2609"
CONTRACT = "PVC2609"
TZ = ZoneInfo("Asia/Shanghai")
KEY_LEVELS = [
    (4617.0, "前结算/09:12剧本压力待破位"),
    (4580.0, "前交易日低点支撑"),
    (4550.0, "前低整数支撑区"),
]

DAY_SESSIONS = [
    (time(9, 0), time(10, 15)),
    (time(10, 30), time(11, 30)),
    (time(13, 30), time(15, 0)),
]
NIGHT_SESSIONS = [
    (time(21, 0), time(23, 0)),
]


def now_cn() -> datetime:
    return datetime.now(TZ)


def in_session(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.time()
    return any(start <= current <= end for start, end in DAY_SESSIONS + NIGHT_SESSIONS)


def fetch_text(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("gbk", errors="replace")


def parse_quote(raw: str) -> dict:
    match = re.search(r'="([^"]*)"', raw)
    if not match:
        raise ValueError(f"unexpected quote response: {raw[:120]}")
    fields = match.group(1).split(",")
    if len(fields) < 15:
        raise ValueError(f"quote has too few fields: {fields}")
    name = fields[0] or CONTRACT
    time_raw = fields[1]
    open_ = float(fields[2])
    high = float(fields[3]) if fields[3] else math.nan
    low = float(fields[4]) if fields[4] else math.nan
    raw_last = float(fields[5]) if fields[5] else math.nan
    bid = float(fields[6]) if fields[6] else math.nan
    ask = float(fields[7]) if fields[7] else math.nan
    last = raw_last
    if math.isnan(last) or last <= 0:
        valid_quotes = [value for value in (bid, ask) if not math.isnan(value) and value > 0]
        if len(valid_quotes) == 2:
            last = sum(valid_quotes) / 2
        elif valid_quotes:
            last = valid_quotes[0]
    if math.isnan(last) or last <= 0:
        raise ValueError("quote last price unavailable")
    oi = float(fields[13]) if fields[13] else math.nan
    volume = float(fields[14]) if fields[14] else math.nan
    date_str = fields[17]
    time_str = f"{time_raw[:2]}:{time_raw[2:4]}:{time_raw[4:6]}" if len(time_raw) == 6 else "00:00:00"
    quote_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    return {
        "name": name,
        "open": open_,
        "last": last,
        "bid": bid,
        "ask": ask,
        "high": high,
        "low": low,
        "volume": volume,
        "open_interest": oi,
        "quote_dt": quote_dt,
        "raw": fields,
    }


def to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, (int, float, str)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return default


def fetch_klines(minutes: int) -> list[dict]:
    url = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_{minutes}=/InnerFuturesNewService.getFewMinLine?symbol=V2609&type={minutes}"
    raw = fetch_text(url)
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end < start:
        return []
    data = json.loads(raw[start:end + 1])
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        dt_raw = item.get("d") or item.get("date") or item.get("datetime")
        close = to_float(item.get("c"), math.nan)
        open_ = to_float(item.get("o"), math.nan)
        high = to_float(item.get("h"), math.nan)
        low = to_float(item.get("l"), math.nan)
        if math.isnan(close) or math.isnan(open_) or math.isnan(high) or math.isnan(low):
            continue
        volume = to_float(item.get("v"), 0.0)
        oi = to_float(item.get("p"), 0.0)
        rows.append({"datetime": dt_raw, "open": open_, "high": high, "low": low, "close": close, "volume": volume, "open_interest": oi})
    return rows


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def append_event(event: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def derive_levels(rows_15m: list[dict], quote: dict) -> dict:
    recent = rows_15m[-32:] if len(rows_15m) >= 8 else []
    last = quote["last"]
    if recent:
        lows = sorted(row["low"] for row in recent)
        highs = sorted(row["high"] for row in recent)
        support = lows[max(0, int(len(lows) * 0.2) - 1)]
        resistance = highs[min(len(highs) - 1, int(len(highs) * 0.8))]
        session_low = min(row["low"] for row in recent)
        session_high = max(row["high"] for row in recent)
    else:
        support = quote["low"] if not math.isnan(quote["low"]) else last - 20
        resistance = quote["high"] if not math.isnan(quote["high"]) else last + 20
        session_low = support
        session_high = resistance
    if support >= last:
        support = min(session_low, last - 8)
    if resistance <= last:
        resistance = max(session_high, last + 8)
    return {
        "support": round(support, 0),
        "resistance": round(resistance, 0),
        "invalidation_long": round(support - 10, 0),
        "invalidation_short": round(resistance + 10, 0),
        "session_low": round(session_low, 0),
        "session_high": round(session_high, 0),
    }


def classify_event(quote: dict, rows_3m: list[dict], rows_15m: list[dict], levels: dict, state: dict, now: datetime) -> dict | None:
    last = quote["last"]
    previous_price = state.get("last_price")
    last_bar = rows_3m[-1] if rows_3m else None
    prev_bar = rows_3m[-2] if len(rows_3m) >= 2 else None
    oi_delta = None
    if last_bar and prev_bar:
        oi_delta = last_bar["open_interest"] - prev_bar["open_interest"]

    support = levels["support"]
    resistance = levels["resistance"]
    events = []
    if last_bar and last_bar["close"] > resistance and (prev_bar is None or prev_bar["close"] <= resistance):
        events.append(("resistance_break", "A", "压力位上破且3m收在其上", "possible_long_or_breakout_confirmed", f"上破 {resistance:.0f}"))
    if last_bar and last_bar["close"] < support and (prev_bar is None or prev_bar["close"] >= support):
        events.append(("support_break", "A", "支撑位跌破且3m未收回", "possible_short_or_breakdown_confirmed", f"跌破 {support:.0f}"))
    for key_level, label in KEY_LEVELS:
        if last_bar and last_bar["close"] < key_level and (prev_bar is None or prev_bar["close"] >= key_level):
            events.append(("key_level_break", "A", f"关键位 {key_level:.0f} 跌破：{label}", "possible_short_or_breakdown_confirmed", f"跌破 {key_level:.0f}"))
    if previous_price is not None:
        previous_price_float = float(previous_price)
        if previous_price_float > 0:
            move = abs(last - previous_price_float)
            if move >= 25:
                direction = "快速上行" if last > previous_price_float else "快速下行"
                events.append(("sharp_move", "A", f"1分钟级别价格{direction}约 {move:.0f} 点", "sharp_move_watch", direction))
    if not events:
        return None

    key, severity, reason, scenario, dedupe_level = events[0]
    dedupe_key = f"{key}:{dedupe_level}"
    last_sent = state.get("last_sent", {}).get(dedupe_key)
    cooldown = 60 if severity == "A" else 600
    if last_sent:
        try:
            last_dt = datetime.fromisoformat(last_sent)
            if now - last_dt < timedelta(seconds=cooldown):
                return None
        except ValueError:
            pass
    return {
        "event_key": key,
        "severity": severity,
        "trigger_reason": reason,
        "scenario_state": scenario,
        "dedupe_key": dedupe_key,
        "oi_delta": oi_delta,
    }


def format_message(quote: dict, levels: dict, event: dict, now: datetime, stale_seconds: float) -> str:
    data_freshness = "实时" if stale_seconds <= 180 else f"疑似延迟 {int(stale_seconds)} 秒"
    oi_note = ""
    if event.get("oi_delta") is not None:
        oi_note = f"；3m持仓变化 {event['oi_delta']:.0f}"
    stop_loss = levels["invalidation_long"] if "long" in event["scenario_state"] or "breakout" in event["scenario_state"] else levels["invalidation_short"]
    targets = f"先看 {levels['resistance']:.0f}/{levels['session_high']:.0f}" if quote["last"] <= levels["resistance"] else f"回看 {levels['support']:.0f}/{levels['session_low']:.0f}"
    return (
        "@所有人\n"
        f"PVC2609｜{now.strftime('%H:%M')}｜期货事件提醒｜现价 {quote['last']:.0f}｜{data_freshness}\n"
        f"触发：{event['trigger_reason']}\n"
        f"状态：{event['scenario_state']}，需结合下一根3m确认，未确认则观望。\n"
        f"关键位：支撑 {levels['support']:.0f}；压力 {levels['resistance']:.0f}；失效/风控 {stop_loss:.0f}\n"
        f"目标观察：{targets}\n"
        f"量仓：公开K线仅可估算量仓变化{oi_note}\n"
        f"备注：公开数据仅一档盘口，无逐笔主动买卖；不是强制交易指令。"
    )


def update_last_price(state: dict, quote: dict) -> None:
    state["last_price"] = quote["last"]
    state["last_quote_time"] = quote["quote_dt"].isoformat()
    save_state(state)


def main() -> int:
    now = now_cn()
    state = load_state()
    if not in_session(now):
        return 0
    try:
        quote = parse_quote(fetch_text(QUOTE_URL))
        stale_seconds = abs((now - quote["quote_dt"]).total_seconds())
        rows_3m = fetch_klines(3)
        rows_15m = fetch_klines(15)
        levels = derive_levels(rows_15m, quote)
        event = classify_event(quote, rows_3m, rows_15m, levels, state, now)
        append_event({"ts": now.isoformat(), "quote_ts": quote["quote_dt"].isoformat(), "price": quote["last"], "levels": levels, "event": event})
        if event:
            state.setdefault("last_sent", {})[event["dedupe_key"]] = now.isoformat()
            update_last_price(state, quote)
            print(format_message(quote, levels, event, now, stale_seconds))
        else:
            update_last_price(state, quote)
    except Exception as exc:
        append_event({"ts": now.isoformat(), "error": str(exc)})
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
