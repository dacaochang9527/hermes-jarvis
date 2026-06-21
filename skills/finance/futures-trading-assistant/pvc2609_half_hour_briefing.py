#!/usr/bin/env python3
"""PVC2609 half-hour briefing for Hermes cron.

Prints one simplified briefing during trading sessions when cooldown allows.
"""
from __future__ import annotations

import json
import math
import re
import urllib.request
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime" / "pvc2609_feishu_monitor"
STATE_PATH = RUNTIME_DIR / "briefing_state.json"
BRIEFING_LOG = RUNTIME_DIR / "half_hour_briefings.jsonl"
QUOTE_URL = "https://hq.sinajs.cn/list=nf_V2609"
CONTRACT = "PVC2609"
TZ = ZoneInfo("Asia/Shanghai")
DAY_SESSIONS = [(time(9, 0), time(10, 15)), (time(10, 30), time(11, 30)), (time(13, 30), time(15, 0))]


def now_cn() -> datetime:
    return datetime.now(TZ)


def in_session(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.time()
    return any(start <= current <= end for start, end in DAY_SESSIONS)


def fetch_text(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("gbk", errors="replace")


def parse_quote(raw: str) -> dict:
    match = re.search(r'="([^"]*)"', raw)
    if not match:
        raise ValueError(f"unexpected quote response: {raw[:120]}")
    fields = match.group(1).split(",")
    time_raw = fields[1]
    last = float(fields[5])
    high = float(fields[3]) if fields[3] else math.nan
    low = float(fields[4]) if fields[4] else math.nan
    volume = float(fields[14]) if fields[14] else math.nan
    oi = float(fields[13]) if fields[13] else math.nan
    time_str = f"{time_raw[:2]}:{time_raw[2:4]}:{time_raw[4:6]}" if len(time_raw) == 6 else "00:00:00"
    quote_dt = datetime.strptime(f"{fields[17]} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    return {"last": last, "high": high, "low": low, "volume": volume, "open_interest": oi, "quote_dt": quote_dt}


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
        close = to_float(item.get("c"), math.nan)
        open_ = to_float(item.get("o"), math.nan)
        high = to_float(item.get("h"), math.nan)
        low = to_float(item.get("l"), math.nan)
        if math.isnan(close) or math.isnan(open_) or math.isnan(high) or math.isnan(low):
            continue
        rows.append({
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": to_float(item.get("v"), 0.0),
            "open_interest": to_float(item.get("p"), 0.0),
        })
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


def append_log(record: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with BRIEFING_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def derive_levels(rows_15m: list[dict], quote: dict) -> dict:
    recent = rows_15m[-32:] if len(rows_15m) >= 8 else []
    last = quote["last"]
    if recent:
        lows = sorted(row["low"] for row in recent)
        highs = sorted(row["high"] for row in recent)
        support = lows[max(0, int(len(lows) * 0.2) - 1)]
        resistance = highs[min(len(highs) - 1, int(len(highs) * 0.8))]
    else:
        support = quote["low"] if not math.isnan(quote["low"]) else last - 20
        resistance = quote["high"] if not math.isnan(quote["high"]) else last + 20
    if support >= last:
        support = last - 8
    if resistance <= last:
        resistance = last + 8
    return {"support": round(support, 0), "resistance": round(resistance, 0)}


def trend(rows: list[dict]) -> str:
    if len(rows) < 6:
        return "数据不足"
    recent = rows[-6:]
    first = recent[0]["close"]
    last = recent[-1]["close"]
    slope = last - first
    highs_up = recent[-1]["high"] >= max(row["high"] for row in recent[:-1])
    lows_down = recent[-1]["low"] <= min(row["low"] for row in recent[:-1])
    if slope > 10 and highs_up:
        return "偏强上行"
    if slope < -10 and lows_down:
        return "偏弱下行"
    return "震荡整理"


def volume_oi_note(rows_3m: list[dict]) -> str:
    if len(rows_3m) < 6:
        return "量仓数据不足"
    recent = rows_3m[-1]
    previous = rows_3m[-2]
    avg_volume = sum(row["volume"] for row in rows_3m[-6:-1]) / 5
    vol_state = "放量" if avg_volume and recent["volume"] > avg_volume * 1.3 else "量能一般"
    oi_delta = recent["open_interest"] - previous["open_interest"]
    return f"{vol_state}，3m持仓变化 {oi_delta:.0f}"


def should_send(now: datetime, state: dict) -> bool:
    last_sent = state.get("last_sent_at")
    if not last_sent:
        return True
    try:
        last_dt = datetime.fromisoformat(last_sent)
    except ValueError:
        return True
    return now - last_dt >= timedelta(minutes=25)


def format_message(now: datetime, quote: dict, levels: dict, rows_3m: list[dict], rows_15m: list[dict], stale_seconds: float) -> str:
    data_freshness = "实时" if stale_seconds <= 180 else f"疑似延迟 {int(stale_seconds)} 秒"
    trend_3m = trend(rows_3m)
    trend_15m = trend(rows_15m)
    if trend_3m.startswith("偏强") and trend_15m.startswith("偏强"):
        direction = "短线偏强，关注压力位能否有效站稳"
    elif trend_3m.startswith("偏弱") and trend_15m.startswith("偏弱"):
        direction = "短线偏弱，关注支撑位能否守住"
    else:
        direction = "多空仍在震荡，先看关键位确认"
    return (
        "@所有人\n"
        f"PVC2609｜{now.strftime('%H:%M')}｜半小时简报｜现价 {quote['last']:.0f}｜{data_freshness}\n"
        f"走势：{direction}\n"
        f"结构：3m {trend_3m}；15m {trend_15m}\n"
        f"点位：支撑 {levels['support']:.0f}；压力 {levels['resistance']:.0f}；下一观察为靠近点位后的3m收线确认\n"
        f"量仓：{volume_oi_note(rows_3m)}\n"
        f"备注：本简报只给走势与点位，不给直接操作建议；公开数据无逐笔主动买卖。"
    )


def main() -> int:
    now = now_cn()
    if not in_session(now):
        return 0
    state = load_state()
    if not should_send(now, state):
        return 0
    try:
        quote = parse_quote(fetch_text(QUOTE_URL))
        rows_3m = fetch_klines(3)
        rows_15m = fetch_klines(15)
        levels = derive_levels(rows_15m, quote)
        stale_seconds = abs((now - quote["quote_dt"]).total_seconds())
        message = format_message(now, quote, levels, rows_3m, rows_15m, stale_seconds)
        state["last_sent_at"] = now.isoformat()
        save_state(state)
        append_log({"ts": now.isoformat(), "quote_ts": quote["quote_dt"].isoformat(), "price": quote["last"], "levels": levels})
        print(message)
    except Exception as exc:
        append_log({"ts": now.isoformat(), "error": str(exc)})
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
