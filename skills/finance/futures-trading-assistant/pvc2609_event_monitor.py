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
PREDICTION_LEVELS_PATH = RUNTIME_DIR / "latest_prediction_levels.json"
SEVERITY_A_COOLDOWN_SECONDS = 600
SEVERITY_B_COOLDOWN_SECONDS = 600
SAME_LEVEL_CHOP_LIMIT = 3
SAME_LEVEL_SUPPRESS_SECONDS = 1800
REENTRY_RESET_POINTS = 6
NEAR_KEY_LEVEL_DISTANCE = 5

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


def optional_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_prediction_level(item: dict) -> list[dict]:
    role = str(item.get("role") or "watch")
    label = str(item.get("label") or item.get("role") or "预测关键位")
    direction = str(item.get("direction") or "both")
    range_low = optional_float(item.get("range_low") or item.get("low"))
    range_high = optional_float(item.get("range_high") or item.get("high"))
    price = optional_float(item.get("price"))
    if price is None and isinstance(item.get("price"), str):
        numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", str(item.get("price")))]
        if len(numbers) >= 2:
            range_low, range_high = min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
        elif numbers:
            price = numbers[0]
    prices = [price] if price is not None else []
    if not prices and range_low is not None and range_high is not None:
        prices = [range_low, range_high]

    normalized = []
    for index, level_price in enumerate(prices):
        if level_price <= 0:
            continue
        boundary = ""
        if len(prices) == 2:
            boundary = "下沿" if index == 0 else "上沿"
        normalized.append({
            "price": level_price,
            "role": f"{role}_{'low' if index == 0 else 'high'}" if boundary and role not in ("watch", "support", "resistance") else role,
            "label": f"{label}{boundary}" if boundary and boundary not in label else label,
            "direction": direction,
            "group_id": str(item.get("group_id") or "") or None,
            "range_low": range_low,
            "range_high": range_high,
        })
    return normalized


def load_prediction_levels() -> dict:
    if not PREDICTION_LEVELS_PATH.exists():
        return {"levels": [], "source_doc": None}
    try:
        data = json.loads(PREDICTION_LEVELS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"levels": [], "source_doc": None}
    clean_levels = []
    for item in data.get("levels", []):
        if not isinstance(item, dict):
            continue
        clean_levels.extend(normalize_prediction_level(item))
    return {
        "levels": clean_levels,
        "source_doc": data.get("source_doc"),
        "updated_at": data.get("updated_at"),
        "session": data.get("session"),
    }


def derive_levels(rows_15m: list[dict], quote: dict, prediction_state: dict | None = None) -> dict:
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
    prediction_state = prediction_state or {"levels": []}
    prediction_levels = prediction_state.get("levels", [])
    lower_levels = [item["price"] for item in prediction_levels if item["price"] <= last]
    upper_levels = [item["price"] for item in prediction_levels if item["price"] >= last]
    if lower_levels:
        support = max(lower_levels)
    if upper_levels:
        resistance = min(upper_levels)
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
        "prediction_levels": prediction_levels,
        "prediction_source": prediction_state.get("source_doc"),
    }


def event_level_price(dedupe_level: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", dedupe_level)
    if not match:
        return None
    return float(match.group(1))


def bar_identity(bar: dict | None) -> str | None:
    if not bar:
        return None
    return str(bar.get("datetime") or "")


def suppress_choppy_level(state: dict, dedupe_key: str, dedupe_level: str, now: datetime) -> bool:
    level_state = state.setdefault("level_state", {}).setdefault(dedupe_key, {})
    suppressed_until = level_state.get("suppressed_until")
    if suppressed_until:
        try:
            if now < datetime.fromisoformat(suppressed_until):
                return True
        except ValueError:
            pass
    level_state["cross_count"] = int(level_state.get("cross_count") or 0) + 1
    level_state["last_cross_at"] = now.isoformat()
    if level_state["cross_count"] >= SAME_LEVEL_CHOP_LIMIT:
        level_state["suppressed_until"] = (now + timedelta(seconds=SAME_LEVEL_SUPPRESS_SECONDS)).isoformat()
        level_state["last_suppress_reason"] = f"{dedupe_level} 反复穿越，暂按震荡区降噪"
        return True
    return False


def maybe_reset_level_state(state: dict, quote: dict) -> None:
    price = quote["last"]
    for dedupe_key, level_state in state.get("level_state", {}).items():
        level_price = event_level_price(dedupe_key)
        if level_price is None:
            continue
        if abs(price - level_price) >= REENTRY_RESET_POINTS:
            level_state["cross_count"] = 0
            level_state.pop("suppressed_until", None)


def maybe_near_key_level_event(last: float, previous_price: object, levels: dict) -> tuple[str, str, str, str, str] | None:
    candidates = []
    for item in levels.get("prediction_levels", []):
        key_level = item["price"]
        distance = abs(last - key_level)
        if distance > NEAR_KEY_LEVEL_DISTANCE:
            continue
        if previous_price is not None:
            try:
                previous_distance = abs(float(previous_price) - key_level)
            except (TypeError, ValueError):
                previous_distance = NEAR_KEY_LEVEL_DISTANCE + 1
            if previous_distance <= NEAR_KEY_LEVEL_DISTANCE:
                continue
        candidates.append((distance, key_level, item))
    if not candidates:
        return None
    _, key_level, item = sorted(candidates, key=lambda value: value[0])[0]
    label = item.get("label") or "预测关键位"
    reason = f"接近预测关键位 {key_level:.0f}（{label}），等待3m收线确认"
    return ("near_key_level", "B", reason, "near_key_level_wait_for_3m_confirmation", f"接近预测位 {key_level:.0f}")


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
    for item in levels.get("prediction_levels", []):
        key_level = item["price"]
        label = item["label"]
        direction = item.get("direction", "both")
        if last_bar and direction in ("both", "down") and last_bar["close"] < key_level and (prev_bar is None or prev_bar["close"] >= key_level):
            events.append(("prediction_level_break", "A", f"预测关键位 {key_level:.0f} 跌破：{label}", "possible_short_or_breakdown_confirmed", f"跌破预测位 {key_level:.0f}"))
        if last_bar and direction in ("both", "up") and last_bar["close"] > key_level and (prev_bar is None or prev_bar["close"] <= key_level):
            events.append(("prediction_level_reclaim", "A", f"预测关键位 {key_level:.0f} 收回/上破：{label}", "possible_long_or_repair_confirmed", f"收回预测位 {key_level:.0f}"))
    if previous_price is not None:
        previous_price_float = float(previous_price)
        if previous_price_float > 0:
            move = abs(last - previous_price_float)
            if move >= 25:
                direction = "快速上行" if last > previous_price_float else "快速下行"
                events.append(("sharp_move", "A", f"1分钟级别价格{direction}约 {move:.0f} 点", "sharp_move_watch", direction))
    near_event = maybe_near_key_level_event(last, previous_price, levels)
    if near_event:
        events.append(near_event)
    if not events:
        return None

    key, severity, reason, scenario, dedupe_level = events[0]
    dedupe_key = f"{key}:{dedupe_level}"
    current_bar_id = bar_identity(last_bar)
    level_state = state.setdefault("level_state", {}).setdefault(dedupe_key, {})
    if current_bar_id and level_state.get("last_sent_bar_id") == current_bar_id:
        return None
    last_sent = state.get("last_sent", {}).get(dedupe_key)
    cooldown = SEVERITY_A_COOLDOWN_SECONDS if severity == "A" else SEVERITY_B_COOLDOWN_SECONDS
    if last_sent:
        try:
            last_dt = datetime.fromisoformat(last_sent)
            if now - last_dt < timedelta(seconds=cooldown):
                return None
        except ValueError:
            pass
    if suppress_choppy_level(state, dedupe_key, dedupe_level, now):
        return None
    level_state["last_sent_bar_id"] = current_bar_id
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
    if event.get("event_key") == "near_key_level":
        return (
            "@所有人\n"
            f"PVC2609｜{now.strftime('%H:%M')}｜接近关键位提醒｜现价 {quote['last']:.0f}｜{data_freshness}\n"
            f"触发：{event['trigger_reason']}\n"
            "状态：只提示接近关键位，等待3m收线确认；未确认则继续观望。\n"
            f"点位：支撑 {levels['support']:.0f}；压力 {levels['resistance']:.0f}\n"
            f"量仓：公开K线仅可估算量仓变化{oi_note}\n"
            "备注：本提醒不是开仓建议；公开数据仅一档盘口，无逐笔主动买卖。"
        )
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
    maybe_reset_level_state(state, quote)
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
        prediction_state = load_prediction_levels()
        levels = derive_levels(rows_15m, quote, prediction_state)
        event = classify_event(quote, rows_3m, rows_15m, levels, state, now)
        append_event({"ts": now.isoformat(), "quote_ts": quote["quote_dt"].isoformat(), "price": quote["last"], "levels": levels, "prediction_source": prediction_state.get("source_doc"), "event": event})
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
