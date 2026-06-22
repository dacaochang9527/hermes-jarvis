#!/usr/bin/env python3
"""PVC2609 pre-open guard check for Hermes cron.

Runs before the futures monitor starts and prints a Feishu-ready status message.
It does not make trading judgments; it verifies delivery/runtime/data readiness.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "configs" / "pvc2609_feishu_monitor.yaml"
RUNTIME_DIR = BASE_DIR / "runtime" / "pvc2609_feishu_monitor"
EVENT_STATE_PATH = RUNTIME_DIR / "last_alert_state.json"
BRIEFING_STATE_PATH = RUNTIME_DIR / "briefing_state.json"
QUOTE_URL = "https://hq.sinajs.cn/list=nf_V2609"
TZ = ZoneInfo("Asia/Shanghai")
CONTRACT = "PVC2609"
REQUIRED_CRON_NAMES = ["PVC2609期货事件监控", "PVC2609期货半小时简报"]


def now_cn() -> datetime:
    return datetime.now(TZ)


def fetch_text(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("gbk", errors="replace")


def parse_quote(raw: str) -> dict:
    match = re.search(r'="([^"]*)"', raw)
    if not match:
        raise ValueError(f"unexpected quote response: {raw[:120]}")
    fields = match.group(1).split(",")
    if len(fields) < 18:
        raise ValueError(f"quote has too few fields: {len(fields)}")
    time_raw = fields[1]
    time_str = f"{time_raw[:2]}:{time_raw[2:4]}:{time_raw[4:6]}" if len(time_raw) == 6 else "00:00:00"
    quote_dt = datetime.strptime(f"{fields[17]} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    raw_last = float(fields[5]) if fields[5] else math.nan
    bid = float(fields[6]) if len(fields) > 6 and fields[6] else math.nan
    ask = float(fields[7]) if len(fields) > 7 and fields[7] else math.nan
    last = raw_last
    if math.isnan(last) or last <= 0:
        valid_quotes = [value for value in (bid, ask) if not math.isnan(value) and value > 0]
        if len(valid_quotes) == 2:
            last = sum(valid_quotes) / 2
        elif valid_quotes:
            last = valid_quotes[0]
    if math.isnan(last) or last <= 0:
        raise ValueError("quote last price unavailable")
    return {
        "last": last,
        "high": float(fields[3]) if fields[3] else math.nan,
        "low": float(fields[4]) if fields[4] else math.nan,
        "open_interest": float(fields[13]) if fields[13] else math.nan,
        "volume": float(fields[14]) if fields[14] else math.nan,
        "quote_dt": quote_dt,
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
        close = to_float(item.get("c"), math.nan)
        open_ = to_float(item.get("o"), math.nan)
        high = to_float(item.get("h"), math.nan)
        low = to_float(item.get("l"), math.nan)
        if math.isnan(close) or math.isnan(open_) or math.isnan(high) or math.isnan(low):
            continue
        rows.append({"open": open_, "high": high, "low": low, "close": close})
    return rows


def check_config(session: str) -> tuple[bool, str]:
    if not CONFIG_PATH.exists():
        return False, "配置文件缺失"
    text = CONFIG_PATH.read_text(encoding="utf-8")
    required = [
        "target: feishu:oc_3b94cfb91274b70374954d7b12f12432",
        "09:00-10:15",
        "10:30-11:30",
        "13:30-15:00",
        "@所有人",
    ]
    if session == "night":
        required.append("21:00-23:00")
    missing = [item for item in required if item not in text]
    if missing:
        return False, "配置缺失：" + "、".join(missing)
    session_label = "夜盘交易时段" if session == "night" else "日盘交易时段"
    return True, f"配置OK：群目标、{session_label}、@所有人模板均存在"


def check_cron_jobs() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["hermes", "cron", "list"],
            cwd=str(BASE_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return False, f"cron列表读取失败：{exc}"
    output = result.stdout or ""
    if result.returncode != 0:
        return False, "cron列表命令失败"
    missing = [name for name in REQUIRED_CRON_NAMES if name not in output]
    if missing:
        return False, "cron任务缺失：" + "、".join(missing)
    disabled = [name for name in REQUIRED_CRON_NAMES if re.search(rf"{re.escape(name)}[\s\S]{{0,240}}enabled\s*[:=]\s*False", output)]
    if disabled:
        return False, "cron任务疑似未启用：" + "、".join(disabled)
    return True, "Cron OK：事件监控与半小时简报任务存在"


def check_data(now: datetime) -> tuple[bool, str]:
    quote = parse_quote(fetch_text(QUOTE_URL))
    rows_3m = fetch_klines(3)
    rows_15m = fetch_klines(15)
    issues = []
    if math.isnan(quote["last"]) or quote["last"] <= 0:
        issues.append("现价异常")
    if len(rows_3m) < 6:
        issues.append(f"3m K线不足({len(rows_3m)})")
    if len(rows_15m) < 6:
        issues.append(f"15m K线不足({len(rows_15m)})")
    quote_age = abs((now - quote["quote_dt"]).total_seconds())
    freshness = "盘前可能为上一交易日快照" if quote_age > 180 else "实时窗口内"
    detail = f"行情OK：现价 {quote['last']:.0f}，quote {quote['quote_dt'].strftime('%m-%d %H:%M:%S')}，3m {len(rows_3m)}条，15m {len(rows_15m)}条，{freshness}"
    if issues:
        return False, detail + "；问题：" + "、".join(issues)
    return True, detail


def check_state_files() -> tuple[bool, str]:
    bad = []
    for path in [EVENT_STATE_PATH, BRIEFING_STATE_PATH]:
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            bad.append(path.name)
    if bad:
        return False, "状态文件JSON异常：" + "、".join(bad)
    return True, "状态OK：cooldown/dedupe文件可读或尚未生成"


def format_message(now: datetime, session: str, checks: list[tuple[str, bool, str]]) -> str:
    all_ok = all(ok for _, ok, _ in checks)
    status = "通过" if all_ok else "未通过"
    if session == "night":
        check_time = "20:50"
        title = "夜盘开盘前守门校验"
        next_text = "21:00后进入夜盘事件监控，半小时简报同步待命"
        reminder = "提醒：夜盘盘前不做交易判断；21:00后若行情延迟超过180秒，将标记疑似延迟并避免强操作结论。"
    else:
        check_time = "08:50"
        title = "开盘前守门校验"
        next_text = "09:00后进入事件监控，半小时简报同步待命"
        reminder = "提醒：盘前不做交易判断；09:00后若行情延迟超过180秒，将标记疑似延迟并避免强操作结论。"
    lines = [
        "@所有人",
        f"PVC2609｜{check_time}｜{title}",
        f"状态：{status}；{next_text}",
    ]
    for label, ok, detail in checks:
        mark = "✓" if ok else "✗"
        lines.append(f"{mark} {label}：{detail}")
    lines.append(reminder)
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PVC2609 pre-open guard check")
    parser.add_argument("--session", choices=["day", "night"], default="day")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = now_cn()
    checks: list[tuple[str, bool, str]] = []
    for label, fn in [
        ("配置", lambda: check_config(args.session)),
        ("Cron", check_cron_jobs),
        ("行情", lambda: check_data(now)),
        ("状态文件", check_state_files),
    ]:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, str(exc)
        checks.append((label, ok, detail))
    print(format_message(now, args.session, checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
