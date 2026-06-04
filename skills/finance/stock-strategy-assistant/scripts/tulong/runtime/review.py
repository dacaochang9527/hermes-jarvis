from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import sys

PROJECT = Path(__file__).resolve().parents[3]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.tulong.runtime.watchdog import load_watchlist, fetch_quotes, entry_zone, format_money_yi

REPORT_DIR = PROJECT / 'reports/reviews'
ALERT_DIR = PROJECT / 'reports/alerts'
TRADES_PATH = PROJECT / 'data/trades/tulong_trades.csv'


def today() -> str:
    return datetime.now().strftime('%Y%m%d')


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_snapshots(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def fnum(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def load_trade_rows(path: Path = TRADES_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def classify_trade(row: dict[str, str], active_codes: set[str], radar_codes: set[str], review_date: str) -> str:
    if (row.get('trade_date') or '').replace('-', '') != review_date:
        return 'other_day'
    name = row.get('name', '')
    note = row.get('note', '')
    code = str(row.get('code', '')).zfill(6)
    session = row.get('session_label') or row.get('position_ref') or ''
    text = f'{name} {note} {session}'.upper()
    if 'ETF' in text or '基金' in text or code.startswith(('510', '511', '512', '513', '515', '516', '517', '518', '159', '588')):
        return 'ETF'
    if code in active_codes:
        return 'D3 active交易'
    if code in radar_codes:
        return 'D3 radar观察但未买'
    if 'HOLD' in text or (row.get('position_ref') and row.get('position_ref') != row.get('session_label')):
        return 'HOLD管理'
    return '策略外交易'


def summarize_trade_attribution(watchlist: list[dict[str, Any]], review_date: str) -> dict[str, list[dict[str, str]]]:
    active_codes = {item['code'] for item in watchlist if item.get('pool_type') == 'watch' and (item.get('pool_subtype') or 'active') == 'active'}
    radar_codes = {item['code'] for item in watchlist if item.get('pool_type') == 'watch' and item.get('pool_subtype') == 'radar'}
    buckets = {
        'D3 active交易': [],
        'D3 radar观察但未买': [],
        'HOLD管理': [],
        '策略外交易': [],
        'ETF': [],
    }
    for row in load_trade_rows():
        bucket = classify_trade(row, active_codes, radar_codes, review_date)
        if bucket in buckets:
            buckets[bucket].append(row)
    return buckets


def summarize_snapshots(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get('code', '')].append(row)
    out: dict[str, dict[str, Any]] = {}
    for code, items in grouped.items():
        prices = [fnum(x.get('price')) for x in items if fnum(x.get('price')) > 0]
        if not prices:
            continue
        out[code] = {
            'samples': len(items),
            'first': prices[0],
            'last': prices[-1],
            'high': max(prices),
            'low': min(prices),
            'first_time': items[0].get('local_time', ''),
            'last_time': items[-1].get('local_time', ''),
        }
    return out


def render_review() -> str:
    now = datetime.now()
    date_key = today()
    watchlist = load_watchlist()
    events = load_jsonl(ALERT_DIR / f'tulong_d3_events_{date_key}.jsonl')
    snapshots = load_snapshots(ALERT_DIR / f'tulong_d3_snapshots_{date_key}.csv')
    snap_summary = summarize_snapshots(snapshots)
    try:
        quotes = fetch_quotes(watchlist)
    except Exception:
        quotes = {}

    event_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        event_by_code[str(event.get('code', ''))].append(event)

    trade_buckets = summarize_trade_attribution(watchlist, date_key)
    active_count = sum(1 for item in watchlist if item.get('pool_type') == 'watch' and (item.get('pool_subtype') or 'active') == 'active')
    radar_count = sum(1 for item in watchlist if item.get('pool_type') == 'watch' and item.get('pool_subtype') == 'radar')
    hold_count = sum(1 for item in watchlist if item.get('pool_type') == 'position' or item.get('stage') == 'HOLD')
    lines = [
        f'# 屠龙D3盘中复盘 {now:%Y-%m-%d}',
        '',
        f'生成时间：{now:%Y-%m-%d %H:%M:%S}',
        '',
        '## 总览',
        '',
        f'- 监控标的：{len(watchlist)} 只（active {active_count} / radar {radar_count} / HOLD {hold_count}）',
        f'- 行情快照记录：{len(snapshots)} 条',
        f'- 结构化事件记录：{len(events)} 条',
        '- 口径：观察、买入时机提示、风险/失效提醒；不是确定性交易指令。',
        '',
        '## 交易归因',
        '',
    ]
    for bucket_name, rows in trade_buckets.items():
        lines.append(f'### {bucket_name}（{len(rows)}笔）')
        if rows:
            for row in rows:
                lines.append(f'- {row.get("action", "")}｜{row.get("code", "")} {row.get("name", "")}｜数量 {row.get("quantity", "")}｜价格 {row.get("price", "")}｜ref {row.get("position_ref", "") or row.get("session_label", "")}｜{row.get("note", "")}')
        else:
            lines.append('- 无')
        lines.append('')
    lines.extend(['## 个股复盘', ''])

    for item in watchlist:
        code = item['code']
        q = quotes.get(code, {})
        trigger = float(item['trigger_price'])
        invalid = float(item['invalid_price'])
        zone_low, zone_high = entry_zone(item)
        s = snap_summary.get(code, {})
        evs = event_by_code.get(code, [])
        alert_evs = [e for e in evs if e.get('event') != 'snapshot_no_alert']
        price = fnum(q.get('price'))
        pct = fnum(q.get('pct'))
        lines.extend([
            f'### {code} {item["name"]}',
            '',
            f'- 当前/收盘附近价：{price:.2f}（{pct:.2f}%），成交额：{format_money_yi(fnum(q.get("amount")))}' if q else '- 当前行情：获取失败',
            f'- 观察价：{trigger:.2f}；失效位：{invalid:.2f}；低吸观察区：{zone_low:.2f}–{zone_high:.2f}',
            f'- 监控样本：{s.get("samples", 0)} 条；监控内高/低：{fnum(s.get("high")):.2f}/{fnum(s.get("low")):.2f}' if s else '- 监控样本：暂无',
        ])
        if alert_evs:
            lines.append('- 今日触发：')
            for e in alert_evs[-6:]:
                lines.append(f'  - {e.get("local_time", "")}｜{e.get("title", e.get("event"))}｜{e.get("reason", "")}')
        else:
            lines.append('- 今日触发：暂无关键告警')
        if price <= invalid and price > 0:
            conclusion = '已跌破失效位，明日从观察池移除或只做风险跟踪。'
        elif zone_low <= price <= zone_high:
            conclusion = '仍在买入观察区，明日重点看承接和是否跌破失效位。'
        elif price > zone_high:
            conclusion = '已脱离低吸区，明日不追高，等待回踩观察价附近或新结构确认。'
        else:
            conclusion = '低于观察区但未必失效，明日优先看是否止跌，弱则放弃。'
        lines.extend([f'- 复盘结论：{conclusion}', ''])

    lines.extend([
        '## 日志文件',
        '',
        f'- 事件 JSONL：`reports/alerts/tulong_d3_events_{date_key}.jsonl`',
        f'- 行情快照 CSV：`reports/alerts/tulong_d3_snapshots_{date_key}.csv`',
        '- 普通运行日志：`reports/alerts/tulong_d3_monitor.log`',
        '',
    ])
    return '\n'.join(lines)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f'tulong_d3_review_{today()}.md'
    report = render_review()
    path.write_text(report, encoding='utf-8')
    print(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
