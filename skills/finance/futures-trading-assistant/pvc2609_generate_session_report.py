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
    "morning": [(time(9, 0), time(10, 15)), (time(10, 30), time(11, 30))],
    "day": [(time(9, 0), time(10, 15)), (time(10, 30), time(11, 30)), (time(13, 30), time(15, 0))],
    "night": [(time(21, 0), time(23, 0))],
}

SESSION_TITLES = {
    "morning": "上午盘",
    "afternoon": "午盘",
    "day": "日盘",
    "night": "夜盘",
    "next_day_day": "日盘",
}

DEFAULT_NEXT_SESSION = {
    "morning": "afternoon",
    "day": "night",
    "night": "next_day_day",
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


def session_title(session: str) -> str:
    return SESSION_TITLES.get(session, session)


def relative_report_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR))
    except ValueError:
        return str(path)


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
    elif session == "morning":
        candidates = [REPORTS_DIR / f"pvc2609_{trading_date:%Y%m%d}_morning_preopen_review_forecast.md"]
        candidates.extend(
            REPORTS_DIR / f"pvc2609_{trading_date - timedelta(days=offset):%Y%m%d}_night_review_next_day_plan.md"
            for offset in range(1, 8)
        )
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



def price_token(value: float | str) -> str:
    if isinstance(value, str):
        return value
    return fmt_price(value)


def price_band(low: float, high: float) -> str:
    return f"{fmt_price(low)}-{fmt_price(high)}"


def pct_range(low: int, high: int) -> str:
    return f"{low}%-{high}%"


def fmt_volume(value: float) -> str:
    if value is None or math.isnan(value):
        return "N/A"
    return f"{value:,.0f}"


def fmt_oi_delta(value: float) -> str:
    if value is None or math.isnan(value):
        return "N/A"
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:,.0f}"


def first_valid(*values: float, default: float = math.nan) -> float:
    for value in values:
        if value is not None and not math.isnan(value):
            return value
    return default


def nearest_5(value: float) -> float:
    if value is None or math.isnan(value):
        return math.nan
    return round(value / 5) * 5


def row_at_or_before(rows: list[Bar], marker: time) -> Bar | None:
    eligible = [row for row in rows if row.dt and row.dt.time() <= marker]
    return eligible[-1] if eligible else None


def session_segments(rows: list[Bar], session: str) -> list[tuple[str, list[Bar]]]:
    if session == "night":
        windows = [
            ("开盘至前30分钟", time(21, 0), time(21, 30)),
            ("破位后验证段", time(21, 30), time(22, 0)),
            ("中段修复/延续段", time(22, 0), time(22, 40)),
            ("尾段收盘定性段", time(22, 40), time(23, 0)),
        ]
    elif session == "morning":
        windows = [
            ("上午开局", time(9, 0), time(9, 30)),
            ("上午第一主段", time(9, 30), time(10, 15)),
            ("上午续盘确认", time(10, 30), time(11, 0)),
            ("午前收束定性", time(11, 0), time(11, 30)),
        ]
    else:
        windows = [
            ("早盘开局", time(9, 0), time(9, 30)),
            ("早盘主段", time(9, 30), time(10, 15)),
            ("午前确认", time(10, 30), time(11, 30)),
            ("午后至收盘", time(13, 30), time(15, 0)),
        ]
    segments = []
    for label, start, end in windows:
        segment_rows = [row for row in rows if row.dt and start <= row.dt.time() <= end]
        segments.append((label, segment_rows))
    return segments


def segment_sentence(label: str, rows: list[Bar], levels: dict) -> str:
    if not rows:
        return f"{label}：未取得完整K线样本，保留人工核对入口。"
    summary = summarize_bars(rows)
    close = summary["close"]
    open_ = summary["open"]
    low = summary["low"]
    high = summary["high"]
    move = close - open_ if not math.isnan(close) and not math.isnan(open_) else math.nan
    if not math.isnan(move) and move > 10:
        action = "低位回补/修复占优"
    elif not math.isnan(move) and move < -10:
        action = "空头下压占优"
    else:
        action = "区间拉锯"
    extra = []
    if not math.isnan(low) and low <= levels["session_low"] + 1:
        extra.append("触及本阶段低点")
    if not math.isnan(high) and high >= levels["session_high"] - 1:
        extra.append("触及本阶段高点")
    if not math.isnan(close) and close >= levels["resistance"]:
        extra.append("收回/逼近压力区")
    if not math.isnan(close) and close <= levels["support"]:
        extra.append("跌回支撑区附近")
    suffix = "；" + "，".join(extra) if extra else ""
    return f"{label}：区间 `{fmt_price(low)}-{fmt_price(high)}`，收 `{fmt_price(close)}`，节奏为{action}{suffix}。"


def extract_price_mentions(text: str) -> list[str]:
    matches = re.findall(r'(?<!\d)(4\d{3}(?:-4\d{3})?)(?!\d)', text)
    deduped: list[str] = []
    for match in matches:
        if match not in deduped:
            deduped.append(match)
    return deduped[:16]


def extract_prior_scenarios(path: Path | None) -> list[dict[str, str]]:
    fallback = [
        {"name": "方案 A：反抽承压", "trigger": "反抽到近端压力区后3m转弱", "direction": "short"},
        {"name": "方案 B：跌破延续", "trigger": "跌破关键支撑后反抽不过", "direction": "short"},
        {"name": "方案 C：低位守住修复", "trigger": "刺破/守住低位后重新收回中轴", "direction": "repair"},
        {"name": "方案 D：强修复确认", "trigger": "站稳上方确认位并回踩不破", "direction": "long"},
    ]
    if path is None or not path.exists():
        return fallback
    text = path.read_text(encoding="utf-8", errors="ignore")
    scenarios: list[dict[str, str]] = []
    patterns = [
        ("方案 A", r'方案\s*A[^\n#|：:]*[：:]?([^\n|]*)'),
        ("方案 B", r'方案\s*B[^\n#|：:]*[：:]?([^\n|]*)'),
        ("方案 C", r'方案\s*C[^\n#|：:]*[：:]?([^\n|]*)'),
        ("方案 D", r'方案\s*D[^\n#|：:]*[：:]?([^\n|]*)'),
    ]
    for label, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        tail = match.group(1).strip(" ：:-") if match else ""
        name = f"{label}：{tail}" if tail else fallback[len(scenarios)]["name"]
        direction = "repair" if "修复" in name or "反抽" in name and "承压" not in name else "short"
        if "站稳" in name or "多" in name:
            direction = "long"
        if "跌破" in name or "破位" in name:
            direction = "short"
        scenarios.append({"name": name[:42], "trigger": infer_trigger_from_name(name), "direction": direction})
    return scenarios or fallback


def infer_trigger_from_name(name: str) -> str:
    if "承压" in name:
        return "到达压力区后未站稳，并出现3m转弱"
    if "跌破" in name or "破位" in name:
        return "跌破支撑后反抽不过，而不是第一根急跌"
    if "修复" in name or "反抽" in name:
        return "低位不再续跌，重新收回中轴/确认位"
    if "站稳" in name:
        return "站稳上方确认位并回踩不破"
    return "按前序计划触发条件核对"


def evaluate_scenario(scenario: dict[str, str], levels: dict, summary: dict) -> tuple[str, str, str]:
    high = summary["high"]
    low = summary["low"]
    close = summary["close"]
    direction = scenario.get("direction", "range")
    if direction == "short" and not math.isnan(low) and low <= levels["session_low"] + 1 and close > levels["support"]:
        return "部分触发但延续失败", "有低位刺破/下探，但随后收回支撑或中轴，破位延续确认不足", "第一根急跌不能追，必须等反抽不过"
    if direction == "short" and high >= levels["resistance"] and close < levels["resistance"]:
        return "基本触发", "价格进入压力区后未能继续站稳", "可按承压转弱处理，但止损必须贴近确认位"
    if direction in ("repair", "long") and close >= levels["close"] and high >= levels["resistance"]:
        return "基本相符", "低位未延续下行，后段收回中轴并逼近/突破压力区", "只按修复处理，不直接定义趋势反转"
    if direction == "long" and close < levels["upper_confirm"]:
        return "部分触及但未确认", "修复出现，但尚未站稳上方确认位", "下一阶段继续观察确认位能否被收回"
    return "未充分触发", "实际路径没有满足完整触发链条", "未触发也要记录，避免事后归因"


def build_plan_levels(levels: dict) -> dict[str, float]:
    low = levels["session_low"]
    high = levels["session_high"]
    close = levels["close"]
    support = nearest_5(min(levels["support"], close - 10))
    pivot_low = nearest_5(min(close, levels["resistance"] - 10))
    pivot_high = nearest_5(max(close, pivot_low + 10))
    pressure_low = nearest_5(max(levels["resistance"], close + 5))
    pressure_high = nearest_5(max(levels["upper_confirm"], pressure_low + 10))
    repair_confirm = nearest_5(pressure_high + 10)
    major_resistance = nearest_5(repair_confirm + 10)
    breakdown_target = nearest_5(min(levels["lower_confirm"], low - 10))
    extreme_target = nearest_5(breakdown_target - 20)
    return {
        "low": nearest_5(low),
        "support": support,
        "pivot_low": pivot_low,
        "pivot_high": pivot_high,
        "close": nearest_5(close),
        "pressure_low": pressure_low,
        "pressure_high": pressure_high,
        "repair_confirm": repair_confirm,
        "major_resistance": major_resistance,
        "breakdown_target": breakdown_target,
        "extreme_target": extreme_target,
        "high": nearest_5(high),
    }


def build_report(args: argparse.Namespace, quote: dict, klines: dict[int, list[Bar]], daily: list[Bar], prior_report: Path | None) -> tuple[str, dict]:
    session_rows_3m = bars_for_session(klines.get(3, []), args.date, args.session)
    session_rows_15m = bars_for_session(klines.get(15, []), args.date, args.session)
    session_summary = summarize_bars(session_rows_3m or klines.get(3, [])[-80:])
    levels = derive_levels(session_summary, quote, klines.get(15, []))
    plan = build_plan_levels(levels)
    bias = infer_bias(session_summary, daily)
    next_session = args.next_session or DEFAULT_NEXT_SESSION[args.session]
    next_date = args.next_date or (args.date + timedelta(days=1) if args.session == "night" and next_session == "next_day_day" else args.date)
    source_doc = relative_report_path(args.output) if args.output else f"reports/{default_report_name(args.date, args.session)}"
    generated_at = now_cn()
    quote_stale = "是" if quote["quote_dt"].date() != args.date else "否"
    ma5 = moving_average(daily, 5)
    ma10 = moving_average(daily, 10)
    ma20 = moving_average(daily, 20)
    daily_rsi = rsi(daily)
    prior_handoff = extract_handoff(prior_report)
    prior_scenarios = extract_prior_scenarios(prior_report)
    prior_text = prior_report.read_text(encoding="utf-8", errors="ignore") if prior_report and prior_report.exists() else ""
    prior_mentions = extract_price_mentions(prior_text)
    event_records = read_jsonl(EVENT_LOG, args.date, args.session, limit=10)
    briefing_records = read_jsonl(BRIEFING_LOG, args.date, args.session, limit=8)

    title_date = args.date.strftime("%Y-%m-%d")
    next_title = session_title(next_session)
    completed_title = session_title(args.session)
    next_date_text = next_date.strftime("%Y-%m-%d")
    completed_label = f"{title_date} {completed_title}"
    next_label = f"{next_date_text} {next_title}"
    next_label_compact = f"{next_date.strftime('%m%d')} {next_title}"

    open_bar = session_rows_3m[0] if session_rows_3m else None
    close_bar = session_rows_3m[-1] if session_rows_3m else None
    low_bar = min(session_rows_3m, key=lambda row: row.low) if session_rows_3m else None
    high_bar = max(session_rows_3m, key=lambda row: row.high) if session_rows_3m else None
    oi_early = row_at_or_before(session_rows_15m or session_rows_3m, time(21, 30) if args.session == "night" else time(9, 30))
    oi_late = close_bar
    oi_path = "持仓口径不足"
    if oi_early and oi_late:
        delta = oi_late.open_interest - oi_early.open_interest
        oi_path = f"{fmt_volume(oi_early.open_interest)} → {fmt_volume(oi_late.open_interest)}，约 {fmt_oi_delta(delta)} 手"

    if bias == "range_repair":
        core_phrase = "低位假破 + 回补修复"
        bias_sentence = "不是单边续跌，而是先下探后收回的修复结构"
        risk_flags = "auto_generated_full_draft, false_break_low, short_covering_repair, range_trap, one_level_quote_only, no_tick_active_flow"
    elif bias == "bearish":
        core_phrase = "弱势延续 + 反抽待确认"
        bias_sentence = "仍偏弱，反抽如果不能站稳压力位，容易重新回到弱势路径"
        risk_flags = "auto_generated_full_draft, bearish_trend, breakdown_risk, one_level_quote_only, no_tick_active_flow"
    elif bias == "repair":
        core_phrase = "短线修复 + 上方确认"
        bias_sentence = "短线修复更明显，但仍需上方确认位验证是否延续"
        risk_flags = "auto_generated_full_draft, repair_confirmation_needed, range_trap, one_level_quote_only, no_tick_active_flow"
    else:
        core_phrase = "区间震荡 + 边界确认"
        bias_sentence = "中轴区间反复，必须等边界触发而不是在中间追单"
        risk_flags = "auto_generated_full_draft, range_bound, range_trap, one_level_quote_only, no_tick_active_flow"

    segment_lines = [segment_sentence(label, rows, levels) for label, rows in session_segments(session_rows_3m, args.session)]
    segment_numbered = "\n".join(f"{idx}. {line}" for idx, line in enumerate(segment_lines, 1))

    timeframe_rows = []
    if daily:
        latest_daily = daily[-1]
        timeframe_rows.append(["日K", "大周期偏弱/等待修复确认" if latest_daily.close < first_valid(ma5, default=latest_daily.close + 1) else "日K修复观察", f"高 {fmt_price(latest_daily.high)} / 低 {fmt_price(latest_daily.low)} / 收 {fmt_price(latest_daily.close)}", f"MA5/10/20={fmt_price(ma5)}/{fmt_price(ma10)}/{fmt_price(ma20)}，RSI={daily_rsi:.1f}" if not math.isnan(daily_rsi) else f"MA5/10/20={fmt_price(ma5)}/{fmt_price(ma10)}/{fmt_price(ma20)}", "先定大背景，不能用小周期单根K线直接推翻。"])
    for minutes in (120, 60, 30, 15, 3):
        rows = klines.get(minutes, [])
        summary = summarize_bars(bars_for_session(rows, args.date, args.session) or rows[-12:])
        implication = "用于确认边界突破、跌破、回收或承压。"
        if minutes == 3:
            implication = "作为入场触发周期，破位/突破必须看收盘与反抽确认。"
        elif minutes == 15:
            implication = "用于判断修复是否有连续性，避免只看3m噪音。"
        timeframe_rows.append([f"{minutes}m", trend_label(rows), f"区间 {fmt_price(summary['low'])}-{fmt_price(summary['high'])} / 收 {fmt_price(summary['close'])}", f"量 {fmt_volume(summary['volume'])}，持仓变化 {fmt_oi_delta(summary['oi_delta'])}", implication])
    timeframe_md = "\n".join(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |" for row in timeframe_rows)

    validation_rows = []
    for scenario in prior_scenarios[:4]:
        status, reason, implication = evaluate_scenario(scenario, levels, session_summary)
        validation_rows.append(f"| {scenario['name']} | {scenario['trigger']} | 本阶段区间 `{fmt_price(session_summary['low'])}-{fmt_price(session_summary['high'])}`，收 `{fmt_price(session_summary['close'])}` | {status} | {reason} | {implication} |")
    validation_md = "\n".join(validation_rows)

    time_verify_md = "\n".join([
        f"| 开盘 | 先看开盘是否直接脱离前序中轴 | 开盘 `{fmt_price(session_summary['open'])}`，首段表现见分时四段 | 基本用于定性 | 开盘通常噪音大 | 开盘前15-30分钟只观察，不抢第一根方向 |",
        f"| 前30分钟 | 关键低/高位触发后需二次确认 | 低点 `{fmt_price(low_bar.low) if low_bar else 'N/A'}`，高点 `{fmt_price(high_bar.high) if high_bar else 'N/A'}` | 需结合触发链 | 单点触发容易假破/假突破 | 必须看反抽不过或回踩不破 |",
        f"| 主段 | 若收回中轴，低位追空/高位追多降级 | 主段结构：{segment_lines[2] if len(segment_lines) > 2 else '样本不足'} | 自动复核 | 中段决定方向能否延续 | 中轴内不做碎单 |",
        f"| 尾盘/收盘 | 收盘位置决定下一阶段中轴 | 收盘 `{fmt_price(session_summary['close'])}`，相对压力 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}` | 可作为下一阶段起点 | 尾盘冲高/杀跌可能只是回补 | 次时段先验证收盘区是否守住 |",
        f"| 波动区间 | 以前序关键位为边界做验证 | 实际 `{fmt_price(session_summary['low'])}-{fmt_price(session_summary['high'])}`，振幅约 `{fmt_price(session_summary['high'] - session_summary['low'])}` 点 | 区间已量化 | 边界附近最容易出现假动作 | 边界触发必须等待确认 |",
    ])

    monitor_rows = []
    for record in briefing_records or event_records[:5]:
        monitor_rows.append(format_monitor_record(record))
    monitor_md = "\n".join(monitor_rows) or "| 暂无 | N/A | 无本地样本 | 仅用K线复核 |"
    event_note = f"事件日志 {len(read_jsonl(EVENT_LOG, args.date, args.session, limit=1000))} 条样本；半小时简报 {len(read_jsonl(BRIEFING_LOG, args.date, args.session, limit=1000))} 条样本。"

    prior_levels_text = "、".join(prior_mentions[:10]) if prior_mentions else "未从前序文档提取到清晰点位"

    markdown = f"""# PVC2609 {completed_label}复盘 + {next_label}计划

> 生成时间：{generated_at.strftime('%Y-%m-%d %H:%M CST')}  
> 生成方式：`pvc2609_generate_session_report.py` 自动生成完整草稿，需人工复核后作为正式交易文档  
> 标的：PVC2609 期货合约  
> 复盘对象：{completed_label}  
> 前序计划：`{prior_report.relative_to(BASE_DIR) if prior_report else '未找到'}`  
> 数据源：新浪期货公开 quote、3m/15m/30m/60m/120m K线、日K、本地事件监控、本地30分钟简报  
> 数据状态：quote 返回 `{fmt_dt(quote['quote_dt'])}`，当前/收盘参考 `{fmt_price(quote['last'])}`，quote 日期与复盘日期不一致：{quote_stale}  
> 数据限制：公开行情只有一档盘口，不能还原逐笔主动买卖；K线量仓只用于结构参考，不能直接标注多开/空开/多平/空平。  
> 风险提示：本文为交易复盘与条件化计划，不构成确定性投资建议；期货杠杆高，必须先设止损。

## 1. 一句话结论

{completed_label}自动结论为“{core_phrase}”：本阶段区间 `{fmt_price(session_summary['low'])}-{fmt_price(session_summary['high'])}`，收盘/最新参考 `{fmt_price(session_summary['close'])}`，{bias_sentence}。{next_label}主战场先放在 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pressure_high'])}`，上方看 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['repair_confirm'])}` 是否站稳，下方看 `{fmt_price(plan['support'])}/{fmt_price(plan['low'])}` 是否再次失守。

## 2. {completed_title}总评

{completed_title}从 `{fmt_price(session_summary['open'])}` 开始，最低 `{fmt_price(session_summary['low'])}`、最高 `{fmt_price(session_summary['high'])}`，最后收在 `{fmt_price(session_summary['close'])}`。结构上更接近“先验证边界，再回到中轴/压力区”的节奏，而不是单一方向的无条件延续。

这说明：

- 前序关键位 `{prior_levels_text}` 需要按“触发 + 确认”而不是“触碰即成立”来复盘。
- 如果低点 `{fmt_price(session_summary['low'])}` 被打出后没有继续延续，则低位追空逻辑降级；如果高点 `{fmt_price(session_summary['high'])}` 附近不能继续站稳，则修复也不能直接当成趋势反转。
- 本阶段持仓路径 `{oi_path}`，只能说明持仓增减和价格同向/背离关系，不能还原逐笔主动买卖。
- 下一阶段不要在 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}` 中轴凭感觉来回切，应等 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}` 或 `{fmt_price(plan['support'])}/{fmt_price(plan['low'])}` 的边界确认。

## 3. 数据状态与行情摘要

| 项目 | 数值 |
|---|---:|
| quote 时间 | {fmt_dt(quote['quote_dt'])} |
| quote 最新/收盘参考 | {fmt_price(quote['last'])} |
| quote 日内最高 / 最低 | {fmt_price(quote['high'])} / {fmt_price(quote['low'])} |
| {completed_title}K线开盘 / 最高 / 最低 / 收盘 | {fmt_price(session_summary['open'])} / {fmt_price(session_summary['high'])} / {fmt_price(session_summary['low'])} / {fmt_price(session_summary['close'])} |
| 3m K线数量 | {len(session_rows_3m)} 根 |
| 3m 成交量合计 | {fmt_volume(session_summary['volume'])} 手 |
| 3m 持仓变化 | {fmt_oi_delta(session_summary['oi_delta'])} 手 |
| 15m K线数量 | {len(session_rows_15m)} 根 |
| 15m 区间 | {fmt_price(summarize_bars(session_rows_15m)['low'])}-{fmt_price(summarize_bars(session_rows_15m)['high'])} |
| 本地监控样本 | {event_note} |
| 本阶段主路径 | {fmt_dt(open_bar.dt if open_bar else None)} 开始，{fmt_dt(low_bar.dt if low_bar else None)} 附近见低点，{fmt_dt(high_bar.dt if high_bar else None)} 附近见高点，收 `{fmt_price(session_summary['close'])}` |

{completed_title}结构可分为四段：

{segment_numbered}

## 4. 多周期结构总表

| 周期 | 方向/结构 | 关键位 | 指标/量仓状态 | 对 {next_label} 的交易含义 |
|---|---|---|---|---|
{timeframe_md}

多周期结论：大周期先决定方向背景，小周期只决定入场和风控。当前最重要的不是判断一个绝对多空，而是确认 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['repair_confirm'])}` 能否继续收回，或 `{fmt_price(plan['support'])}/{fmt_price(plan['low'])}` 是否有效失守。

## 5. 前序计划逐项验证

| 前序方案 | 计划触发 | 实际路径 | 匹配状态 | 原因 | 执行含义 |
|---|---|---|---|---|---|
{validation_md}

复盘结论：前序计划有效与否，不能只看方向是否最后走对，而要看触发链条是否完整。到位不等于触发，刺破不等于有效跌破，突破不等于趋势反转。

## 6. 时间维度预测 vs 实际验证

| 复盘维度 | 前序预测/计划 | 实际走势 | 相符度 | 偏差来源 | 下次修正 |
|---|---|---|---|---|---|
{time_verify_md}

## 7. 命中/偏差归因与逻辑修正

| 问题类型 | 本次表现 | 造成后果 | 后续规则 |
|---|---|---|---|
| 趋势惯性 | 自动判断 `{bias}`，但具体执行仍要看边界确认 | 容易把大方向理解成任意位置可追 | 大周期定背景，小周期定入场；趋势空/趋势多都不能脱离位置 |
| 关键位确认 | 本阶段低点 `{fmt_price(session_summary['low'])}`、高点 `{fmt_price(session_summary['high'])}` 都需要二次验证 | 单次触碰容易造成假破/假突破 | 看3m/15m收盘、反抽不过或回踩不破 |
| 持仓解释 | 持仓路径 `{oi_path}` | 只能辅助判断回补/增仓倾向，不能写成逐笔事实 | 量仓结论必须写成推断，不标注主动买卖 |
| 执行颗粒 | 中轴 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}` 容易反复 | 高频碎单会被手续费、滑点和假信号消耗 | 只在边界和确认位做决策 |
| 超卖/过热 | 若低位已释放较多波动，继续追击的性价比下降 | 容易在尾段或极端位置被反向修复 | 越到极端位置，越要等反抽/回踩确认 |

## 8. 本地监控与盘面验证

本地监控样本摘要：{event_note}

| 时间 | 价格 | 事件/状态 | 备注 |
|---|---:|---|---|
{monitor_md}

监控结论与K线应一起看：日志负责提示价格触发了什么位置，复盘负责判断触发后是否完成确认。没有逐笔主动买卖数据时，不把单条日志解释成主力行为。

## 9. 关键位变化表

| 点位 | 当前角色 | 验证方式 | {next_label} 新角色 |
|---:|---|---|---|
| {fmt_price(plan['low'])} | 本阶段低点/再破确认位 | 跌破后能否快速收回 | 有效跌破才看新低延续，快速收回则按假破处理 |
| {fmt_price(plan['support'])} | 近端支撑/弱势确认线 | 3m/15m 是否有效跌破 | 跌破且反抽不过，修复逻辑降级 |
| {fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])} | 当前中轴/多空拉锯区 | 能否站稳或跌回 | 中间区不追单，只等向边界移动 |
| {fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])} | 近端压力/承压观察区 | 冲高是否承压，或站稳回踩不破 | 承压可看回落，站稳则修复延续 |
| {fmt_price(plan['repair_confirm'])} | 修复延续确认位 | 站稳后是否回踩不破 | 站稳后停止死空，按修复延续处理 |
| {fmt_price(plan['major_resistance'])} | 大级别修复门槛 | 能否有效收回 | 收回前不轻易改成趋势反转叙事 |
| {fmt_price(plan['breakdown_target'])} | 下方延伸目标 | 支撑失守后是否触及 | 只在跌破确认后使用，不提前挂情绪单 |

## 10. 对 {next_label_compact} 的影响

本次收在 `{fmt_price(session_summary['close'])}`，短线中轴上移/下移到 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}`。{next_title}首先要验证这个中轴能否守住；若守住并继续收回 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['repair_confirm'])}`，说明修复延续；若跌回 `{fmt_price(plan['support'])}` 下方并反抽不过，说明本次修复被回吐。

因此 {next_label} 的主策略应是：

- 不在 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}` 中间位置凭感觉追单。
- 上方看 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}` 是否承压，承压才考虑空。
- 若站稳 `{fmt_price(plan['repair_confirm'])}`，停止死空，按修复延续或空头回补处理。
- 下方看 `{fmt_price(plan['support'])}/{fmt_price(plan['low'])}` 是否重新失守，失守并反抽不过才重新偏弱。

## 11. {next_label_compact}关键点位

| 类型 | 点位 | 含义 |
|---|---:|---|
| 本阶段收盘/中轴 | {fmt_price(plan['close'])} | 下一阶段短线强弱第一观察点 |
| 中轴区间 | {fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])} | 中间反复不交易，等边界触发 |
| 近端压力 | {fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])} | 承压回落或修复延续的分水岭 |
| 修复确认 | {fmt_price(plan['repair_confirm'])} | 站稳后空单逻辑降级 |
| 大级别修复门槛 | {fmt_price(plan['major_resistance'])} | 未站回前不把修复当反转 |
| 近端支撑 | {fmt_price(plan['support'])} | 跌破后看修复是否失败 |
| 本阶段低点 | {fmt_price(plan['low'])} | 再破后必须等反抽不过确认 |
| 下方延伸 | {fmt_price(plan['breakdown_target'])} | 有效跌破后的第一目标区 |
| 极弱延伸 | {fmt_price(plan['extreme_target'])} | 只有放量/增仓跌破后才看 |

## 12. {next_label_compact}情景概率表

| 剧本 | 触发条件 | 预期路径 | 估计概率 | 关键证据 | 失效条件 |
|---|---|---|---:|---|---|
| A：{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])} 承压回落 | 反抽到压力区后3m转弱，不能站稳 `{fmt_price(plan['repair_confirm'])}` | 回看 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}`，再看 `{fmt_price(plan['support'])}` | {pct_range(32, 42)} | 大周期压力仍在，修复后第一压力区容易反复 | 站稳 `{fmt_price(plan['repair_confirm'])}` |
| B：{fmt_price(plan['repair_confirm'])} 修复延续 | 站稳确认位，并回踩 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}` 不破 | 上看 `{fmt_price(plan['major_resistance'])}`，再看更高压力 | {pct_range(24, 34)} | 本阶段若已低位收回，继续修复有回补空间 | 跌回 `{fmt_price(plan['pivot_low'])}` 下方 |
| C：跌回 `{fmt_price(plan['support'])}` 后修复失败 | 跌破支撑，反抽 `{fmt_price(plan['pivot_low'])}` 不过 | 回看 `{fmt_price(plan['low'])}`，再看 `{fmt_price(plan['breakdown_target'])}` | {pct_range(24, 32)} | 中轴失守说明修复被回吐 | 重新站回 `{fmt_price(plan['pivot_high'])}` |
| D：`{fmt_price(plan['low'])}` 再破新低 | 跌破本阶段低点后反抽不过 | 看 `{fmt_price(plan['breakdown_target'])}`，极弱看 `{fmt_price(plan['extreme_target'])}` | {pct_range(16, 24)} | 低点失守会重新释放下行风险 | 跌破后快速收回 `{fmt_price(plan['support'])}` |
| E：无交易区间 | 价格在 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pressure_low'])}` 内反复 | 观望 | — | 空间不足、触发不清 | 突破或跌破边界并确认 |

概率只用于比较剧本优先级，不是统计承诺。若价格一直在中轴内反复，没有必要为了交易而交易。

## 13. {next_label_compact}方案 A：{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])} 承压后的空

适用场景：价格反抽 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}`，但不能站稳，3m 出现冲高回落，15m 没有继续抬高。

| 项目 | 计划 |
|---|---|
| 方向 | 反抽承压空 |
| 入场区 | `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}` 承压后，3m 转弱再考虑 |
| 仓位 | 1 手基础；只有跌回中轴且反抽不过时再考虑加到 2 手 |
| 止损 | `{fmt_price(plan['repair_confirm'])}` 上方；若站稳确认位，空单逻辑降级 |
| 第一止盈 | `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}` |
| 第二止盈 | `{fmt_price(plan['support'])}` |
| 估计概率 | {pct_range(32, 42)} |
| 依据 | 大周期压力未解除，压力区承压仍是顺背景交易 |
| 主要风险 | 若确认位被收回，继续空容易被修复延续挤压 |

执行要点：不要在 `{fmt_price(plan['close'])}` 附近直接开空；必须等压力区承压和3m转弱。若价格没有到压力区或没有转弱，本方案不成立。

## 14. {next_label_compact}方案 B：跌回 `{fmt_price(plan['support'])}` 后的弱势回吐

适用场景：价格跌回 `{fmt_price(plan['support'])}` 下方，且反抽 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}` 不能重新站回。

| 项目 | 计划 |
|---|---|
| 方向 | 修复失败后的回吐空 |
| 入场区 | 跌回 `{fmt_price(plan['support'])}` 后，反抽中轴不过再考虑 |
| 仓位 | 1 手；不追第一根急跌 |
| 止损 | `{fmt_price(plan['pivot_high'])}-{fmt_price(plan['pressure_low'])}`；重新站回中轴后逻辑降级 |
| 第一止盈 | `{fmt_price(plan['low'])}` |
| 第二止盈 | `{fmt_price(plan['breakdown_target'])}` |
| 估计概率 | {pct_range(24, 32)} |
| 依据 | 中轴/支撑失守说明本阶段修复被否定 |
| 主要风险 | 低位已经验证过容易出现假破，必须等反抽不过 |

执行要点：这不是追空方案，而是“修复失败确认”方案。只有跌回支撑且反抽不过，才说明本阶段修复被否定。

## 15. {next_label_compact}方案 C：站稳 `{fmt_price(plan['repair_confirm'])}` 的修复延续

适用场景：价格站稳 `{fmt_price(plan['repair_confirm'])}`，并且回踩 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}` 不破，15m 低点继续抬高。

| 项目 | 计划 |
|---|---|
| 方向 | 修复多 / 空头回补延续 |
| 入场区 | `{fmt_price(plan['repair_confirm'])}` 站稳回踩不破，或压力区被收回后再确认 |
| 仓位 | 1 手；趋势未反转前不加大仓位 |
| 止损 | 跌回 `{fmt_price(plan['pressure_low'])}` 下方，或重新失守中轴 |
| 第一止盈 | `{fmt_price(plan['major_resistance'])}` |
| 第二止盈 | `{fmt_price(plan['major_resistance'] + 20)}` 附近 |
| 估计概率 | {pct_range(24, 34)} |
| 依据 | 若确认位继续收回，说明回补/修复还有延续空间 |
| 主要风险 | 大周期压力仍在，不能把修复多当趋势反转 |

执行要点：多单只做修复，不定义趋势反转。到 `{fmt_price(plan['major_resistance'])}` 必须保护利润；只有继续站稳后，才看更高一档。

## 16. {next_label_compact}方案 D：`{fmt_price(plan['low'])}` 再次跌破后的新低延续

适用场景：价格重新跌破本阶段低点 `{fmt_price(plan['low'])}`，且反抽 `{fmt_price(plan['low'])}-{fmt_price(plan['support'])}` 不能收回。

| 项目 | 计划 |
|---|---|
| 方向 | 新低延续空 |
| 入场区 | 跌破 `{fmt_price(plan['low'])}` 后，反抽 `{fmt_price(plan['low'])}-{fmt_price(plan['support'])}` 不过再考虑 |
| 仓位 | 1 手；不建议第一根破位重仓追 |
| 止损 | 重新站回 `{fmt_price(plan['support'])}` 或 `{fmt_price(plan['pivot_low'])}` |
| 第一止盈 | `{fmt_price(plan['breakdown_target'])}` |
| 第二止盈 | `{fmt_price(plan['extreme_target'])}` |
| 估计概率 | {pct_range(16, 24)} |
| 依据 | 本阶段低点若被有效跌破，说明修复失败并重新释放下行风险 |
| 主要风险 | 连续下探后低位假破概率高，必须等反抽不过确认 |

执行要点：这条方案的纪律最重要。低位刺破很容易快速收回，因此必须等跌破后的反抽确认。

## 17. 方案优先级

| 优先级 | 方案 | 触发条件 | 评价 |
|---:|---|---|---|
| 1 | 方案 A：压力区承压空 | 到 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}` 后3m转弱 | 顺大背景，但必须防止修复延续 |
| 2 | 方案 C：确认位修复延续 | 站稳 `{fmt_price(plan['repair_confirm'])}` | 适合处理低位收回后的继续回补 |
| 3 | 方案 B：支撑跌回后的回吐空 | 跌回 `{fmt_price(plan['support'])}` 且反抽不过 | 用于确认本阶段修复失败 |
| 4 | 方案 D：低点再破新低 | 跌破后反抽不过 `{fmt_price(plan['low'])}-{fmt_price(plan['support'])}` | 有效但低位追空风险最高 |

{next_label}最不应该做的是在 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}` 中间位置凭感觉来回切。这个区间是当前中轴，必须等价格去触碰边界：上方 `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['repair_confirm'])}` 或下方 `{fmt_price(plan['support'])}/{fmt_price(plan['low'])}`。

## 18. 小资金点数现实与风险可行性

PVC 期货每手 5 吨，价格每波动 1 点约 5 元/手。下面不是收益承诺，只用于判断“目标是否现实”。

| 目标盈亏 | 1 手所需点数 | 2 手所需点数 | 3 手所需点数 | 当前行情可行性 | 建议姿态 |
|---|---:|---:|---:|---|---|
| 100 元 | 20 点 | 10 点 | 约 7 点 | 边界触发后较现实 | 到位先保护，不恋战 |
| 200 元 | 40 点 | 20 点 | 约 14 点 | 需要从压力/支撑边界入场 | 只做 A/C/B 的确认触发 |
| 300 元 | 60 点 | 30 点 | 20 点 | 需要完整波段配合 | 不在中轴追单 |
| 500 元 | 100 点 | 50 点 | 约 34 点 | 当日难度较高，容易诱导重仓 | 不建议作为单日硬目标 |

若账户规模较小，日内更应把“控制单笔亏损”放在“赚回亏损”前面。当前更合理的目标不是硬赚固定比例，而是等清晰触发后做 20-40 点的可控波段；若只在中轴内震荡，观望优于碎单。

## 19. {next_label_compact}执行纪律

1. `{fmt_price(plan['low'])}` 若再次跌破，必须等反抽不过，不能第一根追。
2. `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}` 是短线中轴，不是无脑开仓点。
3. `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}` 只有承压转弱才空，站稳则空单降级。
4. `{fmt_price(plan['repair_confirm'])}` 是修复延续确认位；站稳后不要继续死空。
5. 所有空单第一目标先看中轴或近端支撑，到位必须保护，不把短线空变成趋势幻想。
6. 所有多单只按“修复/回补”处理，`{fmt_price(plan['major_resistance'])}` 未站稳前不说趋势反转。

## 20. 最终执行口径

{completed_label}给出的核心信息是：价格在 `{fmt_price(session_summary['low'])}-{fmt_price(session_summary['high'])}` 完成一次边界验证，收在 `{fmt_price(session_summary['close'])}`。所以 {next_label} 不适合简单沿用单方向追击模式，而应围绕 `{fmt_price(plan['support'])}`、`{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}`、`{fmt_price(plan['pressure_low'])}-{fmt_price(plan['repair_confirm'])}` 做条件化执行。

按三句话执行：

- `{fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])} 承压转弱`：可以考虑反抽空，先看 `{fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}`，再看 `{fmt_price(plan['support'])}`。
- `{fmt_price(plan['repair_confirm'])} 站稳`：停止死空，按修复延续处理，先看 `{fmt_price(plan['major_resistance'])}`。
- `{fmt_price(plan['low'])} 再破且反抽不过`：才看新低延续；如果跌破后又快速收回，继续按假破处理。

没有触发就休息。当前位置真正的风险不是只看错大方向，而是在边界没有确认前把逻辑执行得太机械。

```text
STATE_HANDOFF
contract: PVC2609
source_doc: {source_doc}
session_completed: {args.session}
next_session: {next_session}
bias: {bias}
risk_flags: {risk_flags}
must_watch_levels:
  - price: {fmt_price(plan['low'])}
    role: support
    label: 本阶段低点/再破确认位
    trigger: break_down_or_false_break_reclaim
  - price: {fmt_price(plan['support'])}
    role: weakness_confirmation
    label: 近端支撑/修复失败观察
    trigger: lose_or_reclaim
  - price: {fmt_price(plan['pivot_low'])}-{fmt_price(plan['pivot_high'])}
    role: midline
    label: 当前短线中轴
    trigger: hold_or_reject
  - price: {fmt_price(plan['pressure_low'])}-{fmt_price(plan['pressure_high'])}
    role: resistance
    label: 压力区/承压观察
    trigger: rejection_or_break_up
  - price: {fmt_price(plan['repair_confirm'])}
    role: repair_confirmation
    label: 修复延续确认位
    trigger: break_up_or_fail
  - price: {fmt_price(plan['major_resistance'])}
    role: major_resistance
    label: 大级别修复门槛
    trigger: reclaim_or_fail
invalidated_levels:
  - price: {prior_mentions[0] if prior_mentions else 'TBD'}
    reason: 若已被本阶段刺破/收回，单独作为触发信号权重下降，需结合确认链使用
monitor_levels_updated: {str(args.update_levels).lower()}
```
"""

    prediction_payload = {
        "contract": CONTRACT,
        "source_doc": source_doc,
        "updated_at": generated_at.isoformat(),
        "session": next_session,
        "levels": [
            {"price": round(plan["low"]), "role": "support", "label": "本阶段低点/再破确认位", "direction": "down"},
            {"price": round(plan["support"]), "role": "weakness_confirmation", "label": "近端支撑/修复失败观察", "direction": "both"},
            {"price": round(plan["pivot_low"]), "role": "midline_low", "label": "短线中轴下沿", "direction": "both"},
            {"price": round(plan["pressure_low"]), "role": "resistance", "label": "压力区下沿/承压观察", "direction": "both"},
            {"price": round(plan["repair_confirm"]), "role": "repair_confirmation", "label": "修复延续确认位", "direction": "up"},
            {"price": round(plan["major_resistance"]), "role": "major_resistance", "label": "大级别修复门槛", "direction": "up"},
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
    if session == "morning":
        return f"pvc2609_{trading_date:%Y%m%d}_morning_review_afternoon_plan.md"
    if session == "day":
        return f"pvc2609_{trading_date:%Y%m%d}_day_review_night_plan.md"
    return f"pvc2609_{trading_date:%Y%m%d}_night_review_next_day_plan.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PVC2609 session report Markdown draft.")
    parser.add_argument("--date", required=True, type=lambda value: datetime.strptime(value, "%Y%m%d").date(), help="natural trading date, e.g. 20260623")
    parser.add_argument("--session", required=True, choices=("morning", "day", "night"), help="completed session to review")
    parser.add_argument("--next-session", choices=("morning", "afternoon", "night", "next_day_day"), help="next session to forecast; defaults from completed session")
    parser.add_argument("--next-date", type=lambda value: datetime.strptime(value, "%Y%m%d").date(), help="natural date for the next session label")
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
