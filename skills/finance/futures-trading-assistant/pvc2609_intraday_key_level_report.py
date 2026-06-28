#!/usr/bin/env python3
"""PVC2609 intraday key-level trigger report generator.

Runs as a no-agent cron script. When a fresh 3m close effectively crosses one
of the latest prediction key levels, it writes a lightweight operation
re-evaluation Markdown report, publishes it to Feishu, updates the next key
levels, and prints a short group message with the document link.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pvc2609_generate_session_report as generator
from pvc2609_preopen_review_publish import publish_report

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
RUNTIME_DIR = BASE_DIR / "runtime" / "pvc2609_feishu_monitor"
STATE_PATH = RUNTIME_DIR / "intraday_key_level_state.json"
LOG_PATH = RUNTIME_DIR / "intraday_operation_reports.jsonl"
PREDICTION_LEVELS_PATH = RUNTIME_DIR / "latest_prediction_levels.json"
CONTRACT = "PVC2609"
TZ = ZoneInfo("Asia/Shanghai")

MAX_REPORTS_PER_SESSION = 3
SAME_LEVEL_ZONE_POINTS = 5


@dataclass
class KeyLevel:
    price: float
    role: str
    label: str
    direction: str


@dataclass
class Trigger:
    level: KeyLevel
    event_key: str
    direction: str
    reason: str
    bar_time: datetime | None


SESSION_WINDOWS = {
    "morning": [(time(9, 0), time(10, 15)), (time(10, 30), time(11, 30))],
    "afternoon": [(time(13, 30), time(15, 0))],
    "night": [(time(21, 0), time(23, 0))],
}

SESSION_TITLES = {
    "morning": "上午盘",
    "afternoon": "午盘",
    "night": "夜盘",
}


def now_cn() -> datetime:
    return datetime.now(TZ)


def parse_yyyymmdd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def nearest_5(value: float) -> float:
    if math.isnan(value):
        return value
    return round(value / 5) * 5


def fmt_price(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "N/A"
    return f"{value:.0f}"


def fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def current_session(ts: datetime) -> str | None:
    if ts.weekday() >= 5:
        return None
    current = ts.time()
    for session, windows in SESSION_WINDOWS.items():
        if any(start <= current <= end for start, end in windows):
            return session
    return None


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"sessions": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sessions": {}}


def save_state(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_log(record: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def session_key(trading_date: date, session: str) -> str:
    return f"{trading_date:%Y%m%d}:{session}"


def parse_level_price(value: object) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", value)]
        return numbers[:2]
    return []


def load_key_levels() -> tuple[list[KeyLevel], str | None]:
    if not PREDICTION_LEVELS_PATH.exists():
        return [], None
    data = json.loads(PREDICTION_LEVELS_PATH.read_text(encoding="utf-8"))
    levels: list[KeyLevel] = []
    seen: set[tuple[int, str]] = set()
    for item in data.get("levels", []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "watch")
        label = str(item.get("label") or role)
        direction = str(item.get("direction") or "both")
        for price in parse_level_price(item.get("price")):
            if price <= 0:
                continue
            key = (round(price), role)
            if key in seen:
                continue
            seen.add(key)
            levels.append(KeyLevel(price=price, role=role, label=label, direction=direction))
    return levels, data.get("source_doc")


def bars_for_intraday_session(rows: list[generator.Bar], trading_date: date, session: str) -> list[generator.Bar]:
    windows = SESSION_WINDOWS[session]
    return [
        row for row in rows
        if row.dt and row.dt.date() == trading_date and any(start <= row.dt.time() <= end for start, end in windows)
    ]


def summarize(rows: list[generator.Bar]) -> dict:
    if not rows:
        return {"open": math.nan, "high": math.nan, "low": math.nan, "close": math.nan, "volume": 0.0, "oi_delta": math.nan}
    return {
        "open": rows[0].open,
        "high": max(row.high for row in rows),
        "low": min(row.low for row in rows),
        "close": rows[-1].close,
        "volume": sum(row.volume for row in rows),
        "oi_delta": rows[-1].open_interest - rows[0].open_interest,
    }


def find_trigger(levels: list[KeyLevel], rows_3m: list[generator.Bar], force_level: float | None = None) -> Trigger | None:
    if len(rows_3m) < 2:
        return None
    prev_bar = rows_3m[-2]
    last_bar = rows_3m[-1]
    if force_level is not None:
        level = KeyLevel(force_level, "forced", "手动测试触发位", "both")
        return Trigger(level, "forced_trigger", "test", f"手动测试触发 {force_level:.0f}", last_bar.dt)
    for level in sorted(levels, key=lambda item: abs(last_bar.close - item.price)):
        crossed_down = prev_bar.close >= level.price and last_bar.close < level.price
        crossed_up = prev_bar.close <= level.price and last_bar.close > level.price
        if crossed_down and level.direction in ("both", "down"):
            return Trigger(level, "key_level_break_down", "down", f"3m收盘跌破 {level.price:.0f}（{level.label}）", last_bar.dt)
        if crossed_up and level.direction in ("both", "up"):
            return Trigger(level, "key_level_break_up", "up", f"3m收盘收回/上破 {level.price:.0f}（{level.label}）", last_bar.dt)
    return None


def already_triggered(session_state: dict, trigger: Trigger) -> bool:
    if int(session_state.get("report_count") or 0) >= MAX_REPORTS_PER_SESSION:
        return True
    for item in session_state.get("triggered_levels", []):
        try:
            old_price = float(item.get("price"))
        except (TypeError, ValueError):
            continue
        if abs(old_price - trigger.level.price) <= SAME_LEVEL_ZONE_POINTS:
            return True
    return False


def compute_new_levels(trigger: Trigger, quote: dict, session_rows: list[generator.Bar], rows_15m: list[generator.Bar]) -> list[dict]:
    summary = summarize(session_rows or rows_15m[-16:])
    last = quote["last"]
    lows = sorted(row.low for row in (session_rows or rows_15m[-16:]))
    highs = sorted(row.high for row in (session_rows or rows_15m[-16:]))
    support = nearest_5(max([value for value in lows if value <= last] or [last - 15]))
    resistance = nearest_5(min([value for value in highs if value >= last] or [last + 15]))
    midline = nearest_5(last)
    if resistance <= last:
        resistance = nearest_5(last + 15)
    if support >= last:
        support = nearest_5(last - 15)
    if midline <= support:
        midline = nearest_5(support + 5)
    if midline >= resistance:
        midline = nearest_5(resistance - 5)
    if support >= midline:
        support = nearest_5(midline - 5)
    if resistance <= midline:
        resistance = nearest_5(midline + 5)
    lower_confirm = nearest_5(min(support, trigger.level.price) - 10)
    upper_confirm = nearest_5(max(resistance, trigger.level.price) + 10)
    if trigger.direction == "down":
        ordered = [
            {"price": round(lower_confirm), "role": "breakdown_target", "label": "跌破后下方延伸确认", "direction": "down"},
            {"price": round(support), "role": "support", "label": "盘中近端防守/假破观察", "direction": "both"},
            {"price": round(midline), "role": "midline", "label": "触发后短线中轴", "direction": "both"},
            {"price": round(resistance), "role": "retest_resistance", "label": "反抽不过确认位", "direction": "both"},
            {"price": round(upper_confirm), "role": "repair_confirmation", "label": "重新修复确认位", "direction": "up"},
        ]
    elif trigger.direction == "up":
        ordered = [
            {"price": round(support), "role": "support", "label": "回踩不破确认位", "direction": "both"},
            {"price": round(midline), "role": "midline", "label": "触发后短线中轴", "direction": "both"},
            {"price": round(resistance), "role": "resistance", "label": "上方第一压力", "direction": "both"},
            {"price": round(upper_confirm), "role": "repair_confirmation", "label": "修复延续确认位", "direction": "up"},
            {"price": round(lower_confirm), "role": "failure_confirmation", "label": "修复失败确认位", "direction": "down"},
        ]
    else:
        ordered = [
            {"price": round(support), "role": "support", "label": "盘中近端支撑", "direction": "both"},
            {"price": round(midline), "role": "midline", "label": "盘中短线中轴", "direction": "both"},
            {"price": round(resistance), "role": "resistance", "label": "盘中近端压力", "direction": "both"},
        ]
    deduped = []
    seen = set()
    for item in ordered:
        key = (item["price"], item["role"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def probability_rows(trigger: Trigger, new_levels: list[dict]) -> list[tuple[str, str, str, str, str, str]]:
    level_map = {item["role"]: item["price"] for item in new_levels}
    support = fmt_price(float(level_map.get("support", math.nan)))
    resistance = fmt_price(float(level_map.get("resistance", level_map.get("retest_resistance", math.nan))))
    midline = fmt_price(float(level_map.get("midline", math.nan)))
    upper = fmt_price(float(level_map.get("repair_confirmation", math.nan)))
    lower = fmt_price(float(level_map.get("breakdown_target", level_map.get("failure_confirmation", math.nan))))
    if trigger.direction == "down":
        return [
            ("A 弱势延续", f"反抽 {resistance}/{midline} 不过", "38%-45%", "等待反抽不过再考虑空", f"重新站回 {resistance}", f"先看 {support}，再看 {lower}"),
            ("B 假跌破收回", f"跌破后快速收回 {midline}", "25%-32%", "空单降级，观察修复", f"再次跌回 {support}", f"看 {resistance}/{upper}"),
            ("C 中轴震荡", f"价格回到 {support}-{resistance} 内反复", "18%-25%", "不追单，只等边界", "突破/跌破边界", "无固定目标"),
            ("D 强修复", f"站回 {upper}", "10%-16%", "停止死空，按修复处理", f"跌回 {midline}", f"看上方新压力"),
        ]
    if trigger.direction == "up":
        return [
            ("A 修复延续", f"回踩 {support}/{midline} 不破", "36%-44%", "等待回踩不破再考虑多", f"跌回 {support}", f"先看 {resistance}，再看 {upper}"),
            ("B 冲高回落", f"上冲 {resistance} 后不能站稳", "26%-34%", "多单降级，观察承压", f"站稳 {upper}", f"回看 {midline}/{support}"),
            ("C 中轴震荡", f"价格回到 {support}-{resistance} 内反复", "18%-25%", "不追单，只等边界", "突破/跌破边界", "无固定目标"),
            ("D 修复失败", f"跌回 {support}", "10%-16%", "修复逻辑失效，等反抽不过", f"重新站回 {midline}", f"看 {lower}"),
        ]
    return [
        ("A 边界确认", "等待3m/15m继续确认", "30%-38%", "先观察，不抢第一根", "确认失败", "看上下边界"),
        ("B 假触发", "触发后快速收回/跌回", "25%-32%", "不追，等第二次确认", "重新有效触发", "无固定目标"),
        ("C 区间震荡", "关键位附近反复穿越", "25%-32%", "只记录，不重复发文档", "离开区间", "无固定目标"),
    ]


def build_markdown(
    *,
    trading_date: date,
    session: str,
    trigger: Trigger,
    quote: dict,
    source_doc: str | None,
    session_rows: list[generator.Bar],
    rows_15m: list[generator.Bar],
    rows_30m: list[generator.Bar],
    new_levels: list[dict],
    generated_at: datetime,
    report_name: str,
    report_count: int,
) -> str:
    session_title = SESSION_TITLES[session]
    summary_3m = summarize(session_rows)
    summary_15m = summarize(bars_for_intraday_session(rows_15m, trading_date, session))
    summary_30m = summarize(bars_for_intraday_session(rows_30m, trading_date, session))
    prob_md = "\n".join(
        f"| {name} | {condition} | {prob} | {action} | {invalid} | {target} |"
        for name, condition, prob, action, invalid, target in probability_rows(trigger, new_levels)
    )
    levels_md = "\n".join(
        f"| {item['price']} | {item['role']} | {item['label']} | 是，受时段上限约束 |"
        for idx, item in enumerate(new_levels, 1)
    )
    handoff_levels = "\n".join(
        "\n".join([
            f"  - price: {item['price']}",
            f"    role: {item['role']}",
            f"    label: {item['label']}",
            "    trigger: effective_3m_close",
        ])
        for item in new_levels[:5]
    )
    quote_stale = "是" if quote["quote_dt"].date() != trading_date else "否"
    return f"""# PVC2609 {trading_date:%Y-%m-%d} {session_title}盘中关键位触发操作重估

> 生成时间：{generated_at.strftime('%Y-%m-%d %H:%M CST')}  
> 标的：PVC2609 期货合约  
> 触发来源：{source_doc or 'latest_prediction_levels.json'}  
> 数据源：新浪期货公开 quote、3m/15m/30m K线、本地关键位状态  
> 数据状态：quote 返回 `{fmt_dt(quote['quote_dt'])}`，现价 `{fmt_price(quote['last'])}`，quote 日期与交易日不一致：{quote_stale}  
> 风险提示：本文为盘中条件化操作重估，不构成确定性投资建议；没有触发确认就观望。

## 1. 触发概况

| 项目 | 内容 |
|---|---|
| 触发时段 | {session_title} |
| 触发时间 | {fmt_dt(trigger.bar_time)} |
| 触发价位 | {fmt_price(trigger.level.price)} |
| 触发类型 | {trigger.event_key} |
| 触发说明 | {trigger.reason} |
| 触发后现价 | {fmt_price(quote['last'])} |
| 本时段第几份盘中文档 | {report_count}/{MAX_REPORTS_PER_SESSION} |

## 2. 当前结构

| 周期 | 区间 | 收盘/现价 | 量仓 | 解读 |
|---|---|---|---|---|
| 3m 本时段 | {fmt_price(summary_3m['low'])}-{fmt_price(summary_3m['high'])} | {fmt_price(summary_3m['close'])} | 量 {summary_3m['volume']:.0f}；持仓变化 {summary_3m['oi_delta']:.0f} | 入场触发周期，只看有效收线 |
| 15m 本时段 | {fmt_price(summary_15m['low'])}-{fmt_price(summary_15m['high'])} | {fmt_price(summary_15m['close'])} | 量 {summary_15m['volume']:.0f}；持仓变化 {summary_15m['oi_delta']:.0f} | 判断触发是否有连续性 |
| 30m 本时段 | {fmt_price(summary_30m['low'])}-{fmt_price(summary_30m['high'])} | {fmt_price(summary_30m['close'])} | 量 {summary_30m['volume']:.0f}；持仓变化 {summary_30m['oi_delta']:.0f} | 判断是否只是短线噪音 |

## 3. 操作概率表

| 方案 | 条件 | 概率 | 处理 | 失效 | 目标 |
|---|---|---:|---|---|---|
{prob_md}

## 4. 新关键位

| 新关键位 | 类型 | 含义 | 再触发是否发文档 |
|---:|---|---|---|
{levels_md}

## 5. 最终口径

- 这次只说明 `{trigger.reason}` 已经发生，不代表必须立刻交易。
- 下一步优先看新关键位表前三项；同一价位附近 `{SAME_LEVEL_ZONE_POINTS}` 点内不重复生成文档。
- 如果价格回到中轴反复，按横盘陷阱处理，宁可少做，不要让盘中链接刷屏。
- 每个时段最多生成 `{MAX_REPORTS_PER_SESSION}` 份盘中重估文档。

```text
STATE_HANDOFF
contract: PVC2609
source_doc: reports/{report_name}
session_completed: intraday_{session}
next_session: intraday_followup
bias: {trigger.direction}
risk_flags: intraday_trigger, one_level_quote_only, no_tick_active_flow, max_reports_{MAX_REPORTS_PER_SESSION}
must_watch_levels:
{handoff_levels}
monitor_levels_updated: true
```
"""


def report_filename(trading_date: date, session: str, trigger: Trigger, generated_at: datetime) -> str:
    level = round(trigger.level.price)
    stamp = generated_at.strftime("%H%M")
    return f"pvc2609_{trading_date:%Y%m%d}_intraday_{session}_{stamp}_{trigger.event_key}_{level}.md"


def write_prediction_levels(path: Path, source_doc: str, session: str, levels: list[dict]) -> None:
    payload = {
        "contract": CONTRACT,
        "source_doc": source_doc,
        "updated_at": now_cn().isoformat(),
        "session": f"intraday_{session}",
        "levels": levels,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_sent(state: dict, key: str, trigger: Trigger, report_path: Path) -> None:
    session_state = state.setdefault("sessions", {}).setdefault(key, {})
    session_state["report_count"] = int(session_state.get("report_count") or 0) + 1
    session_state.setdefault("triggered_levels", []).append({
        "price": trigger.level.price,
        "role": trigger.level.role,
        "event_key": trigger.event_key,
        "triggered_at": now_cn().isoformat(),
        "report": str(report_path),
    })
    save_state(state)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PVC2609 intraday key-level trigger report.")
    parser.add_argument("--date", type=parse_yyyymmdd, help="trading date, defaults to today")
    parser.add_argument("--session", choices=tuple(SESSION_WINDOWS), help="override current session")
    parser.add_argument("--dry-run", action="store_true", help="generate locally and print message without publishing")
    parser.add_argument("--force-level", type=float, help="force a test trigger at the given price")
    parser.add_argument("--output-dir", type=Path, help="override output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = now_cn()
    trading_date = args.date or now.date()
    session = args.session or current_session(now)
    if session is None and args.force_level is None:
        return 0
    session = session or "morning"

    try:
        quote = generator.parse_quote(generator.fetch_text(generator.QUOTE_URL))
        rows_3m_all = generator.fetch_klines(3)
        rows_15m_all = generator.fetch_klines(15)
        rows_30m_all = generator.fetch_klines(30)
        rows_3m = bars_for_intraday_session(rows_3m_all, trading_date, session)
        if len(rows_3m) < 2 and args.force_level is None:
            return 0
        levels, source_doc = load_key_levels()
        trigger = find_trigger(levels, rows_3m or rows_3m_all[-2:], force_level=args.force_level)
        if trigger is None:
            return 0

        state = load_state()
        key = session_key(trading_date, session)
        session_state = state.setdefault("sessions", {}).setdefault(key, {})
        if already_triggered(session_state, trigger) and args.force_level is None:
            return 0

        session_rows = rows_3m or rows_3m_all[-20:]
        new_levels = compute_new_levels(trigger, quote, session_rows, rows_15m_all)
        generated_at = now_cn()
        filename = report_filename(trading_date, session, trigger, generated_at)
        output_dir = args.output_dir or REPORTS_DIR
        report_path = output_dir / filename
        report_path.parent.mkdir(parents=True, exist_ok=True)
        markdown = build_markdown(
            trading_date=trading_date,
            session=session,
            trigger=trigger,
            quote=quote,
            source_doc=source_doc,
            session_rows=session_rows,
            rows_15m=rows_15m_all,
            rows_30m=rows_30m_all,
            new_levels=new_levels,
            generated_at=generated_at,
            report_name=report_path.name,
            report_count=int(session_state.get("report_count") or 0) + 1,
        )
        report_path.write_text(markdown, encoding="utf-8")
        title = f"PVC2609 {trading_date:%Y-%m-%d} {SESSION_TITLES[session]}盘中关键位触发操作重估"
        published = publish_report(report_path, title, dry_run=args.dry_run)
        url = published.get("url") or "URL生成失败"
        if not args.dry_run:
            write_prediction_levels(PREDICTION_LEVELS_PATH, f"reports/{report_path.name}", session, new_levels)
            mark_sent(state, key, trigger, report_path)
            append_log({"ts": now_cn().isoformat(), "session": session, "trigger": trigger.reason, "report": str(report_path), "url": url})
        print("\n".join([
            title,
            f"飞书文档：{url}",
            f"触发：{trigger.reason}",
            f"本地文件：{report_path}",
        ]))
    except Exception as exc:
        if not args.dry_run:
            append_log({"ts": now_cn().isoformat(), "error": str(exc)})
        else:
            print(f"DRY-RUN error: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
