from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import requests

PROJECT = Path(__file__).resolve().parents[3]
STATE_PATH = PROJECT / 'data/watchlists/tulong_d3_monitor_state.json'
LOG_PATH = PROJECT / 'reports/alerts/tulong_d3_monitor.log'
EVENTS_JSONL_PATH = PROJECT / f'reports/alerts/tulong_d3_events_{datetime.now():%Y%m%d}.jsonl'
SNAPSHOTS_CSV_PATH = PROJECT / f'reports/alerts/tulong_d3_snapshots_{datetime.now():%Y%m%d}.csv'


WATCHLIST = [
    {'code': '600936', 'name': '北投科技', 'trigger_price': 5.78, 'invalid_price': 5.26, 'rank': 1, 'note': '形态最标准，D2量能和回落温和'},
    {'code': '600578', 'name': '京能电力', 'trigger_price': 8.22, 'invalid_price': 7.44, 'rank': 2, 'note': '强度最高但波动大，避免追高'},
    {'code': '003007', 'name': '直真科技', 'trigger_price': 52.64, 'invalid_price': 49.91, 'rank': 3, 'note': 'D2未爆量，股价高、弹性和风险都大'},
    {'code': '603373', 'name': '安邦护卫', 'trigger_price': 50.15, 'invalid_price': 44.23, 'rank': 4, 'note': '形态可看但失效位较远'},
]
ACTIVE_WATCHLIST_CSV_PATH = PROJECT / 'data/watchlists/tulong_active_watchlist.csv'
WATCHLIST_CSV_PATH = ACTIVE_WATCHLIST_CSV_PATH


def load_watchlist() -> list[dict[str, Any]]:
    """Load today's D3 monitor pool from CSV; fall back to the baked-in list."""
    if not WATCHLIST_CSV_PATH.exists():
        return WATCHLIST
    items: list[dict[str, Any]] = []
    try:
        with WATCHLIST_CSV_PATH.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                code = str(row.get('code', '')).zfill(6)
                if not code:
                    continue
                if row.get('pool_type') == 'position' and (row.get('position_status') or '').strip().lower() != 'open':
                    append_log(
                        f'[{datetime.now():%Y-%m-%d %H:%M:%S}] skip_closed_position '
                        f'code={code} status={row.get("position_status") or "空"}'
                    )
                    continue
                items.append({
                    'code': code,
                    'name': row.get('name') or code,
                    'industry': row.get('industry') or '',
                    'stage': row.get('stage') or '',
                    'pool_type': row.get('pool_type') or '',
                    'source_file': row.get('source_file') or '',
                    'trigger_price': float(row['trigger_price']),
                    'invalid_price': float(row['invalid_price']),
                    'zone_low': float(row['zone_low']) if row.get('zone_low') else None,
                    'zone_high': float(row['zone_high']) if row.get('zone_high') else None,
                    'rank': int(float(row.get('rank') or len(items) + 1)),
                    'note': row.get('note', ''),
                    'entry_date': row.get('entry_date') or '',
                    'entry_stage': row.get('entry_stage') or '',
                    'entry_price': float(row['entry_price']) if row.get('entry_price') else None,
                    'quantity': int(float(row['quantity'])) if row.get('quantity') else 0,
                    'sellable_quantity': int(float(row['sellable_quantity'])) if row.get('sellable_quantity') else 0,
                    'cost_amount': float(row['cost_amount']) if row.get('cost_amount') else None,
                    'position_status': row.get('position_status') or '',
                })
    except Exception as e:
        append_log(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] watchlist_load_error {type(e).__name__}: {e}')
        return WATCHLIST
    return items or WATCHLIST

TRADING_WINDOWS = [
    (time(9, 25), time(11, 31)),
    (time(13, 0), time(15, 1)),
]


ALERT_FLUSH_INTERVAL_MINUTES = 5
SNAPSHOT_INTERVAL_MINUTES = 15


def should_run_event_check(now: datetime) -> bool:
    # 每分钟拉行情并检测事件；FORCE_RUN 用于手动验证。
    return True


def should_flush_alerts(now: datetime) -> bool:
    # 微信提醒按 5 分钟节流释放；本地行情/事件仍每分钟记录。
    return os.getenv('FORCE_RUN') == '1' or now.minute % ALERT_FLUSH_INTERVAL_MINUTES == 0


def should_generate_snapshot(now: datetime) -> bool:
    # 快照内容每 15 分钟生成一次，只写本地。
    return now.minute % SNAPSHOT_INTERVAL_MINUTES == 0


def pending_snapshot_due(now: datetime, state: dict[str, Any]) -> bool:
    pending = state.get('pending_snapshot')
    if not isinstance(pending, dict):
        return False
    due_at = pending.get('due_at')
    if not due_at:
        return False
    try:
        return now >= datetime.fromisoformat(due_at)
    except Exception:
        return False


def store_pending_snapshot(state: dict[str, Any], now: datetime, report: str) -> None:
    # 事件与快照撞车时，快照不丢；事件后约 3 分钟补发。只保留最新一份。
    state['pending_snapshot'] = {
        'generated_at': now.isoformat(timespec='seconds'),
        'due_at': (now + timedelta(minutes=3)).isoformat(timespec='seconds'),
        'report': report,
    }


def pop_pending_snapshot(state: dict[str, Any]) -> str | None:
    pending = state.get('pending_snapshot')
    if not isinstance(pending, dict):
        state['pending_snapshot'] = None
        return None
    report = pending.get('report')
    state['pending_snapshot'] = None
    return report if isinstance(report, str) and report else None


def market_prefix(code: str) -> str:
    return ('sh' if code.startswith('6') else 'sz') + code


def is_trading_window(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    t = now.time()
    return any(start <= t <= end for start, end in TRADING_WINDOWS)


def validate_watchlist_date(now: datetime, watchlist: list[dict[str, Any]]) -> bool:
    expected_prefix = f'{now:%m%d}'
    # 仅校验 watch 行的当日日期前缀；position(HOLD) 行无日期、按 entry_date 续期，豁免
    stale = [
        f'{item.get("code", "")}:{item.get("stage", "")}'
        for item in watchlist
        if item.get('pool_type') == 'watch' and not str(item.get('stage', '')).startswith(expected_prefix)
    ]
    if stale:
        append_log(f'[{now:%Y-%m-%d %H:%M:%S}] stale_active_watchlist expected_prefix={expected_prefix} stale={stale}')
        print(
            '【A股监控】实际监控池日期异常，已暂停本轮提醒\n'
            f'期望：{expected_prefix}D3(watch) / HOLD(position)\n'
            f'异常：{", ".join(stale)}'
        )
        return False
    return True


def load_state() -> dict[str, Any]:
    default_state = {
        'last_prices': {},
        'pending_snapshot': None,
        'pending_alerts': [],
        'last_event_run_at': None,
        'last_alert_flush_at': None,
    }
    if not STATE_PATH.exists():
        return default_state.copy()
    try:
        state = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        if isinstance(state, dict):
            state.pop('sent', None)
            for key, value in default_state.items():
                state.setdefault(key, value.copy() if isinstance(value, dict | list) else value)
            if not isinstance(state.get('pending_alerts'), list):
                state['pending_alerts'] = []
            return state
    except Exception:
        pass
    return default_state.copy()


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def append_log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(message + '\n')


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')


def append_snapshot(now: datetime, item: dict[str, Any], q: dict[str, Any]) -> None:
    SNAPSHOTS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    exists = SNAPSHOTS_CSV_PATH.exists()
    row = {
        'local_time': now.isoformat(timespec='seconds'),
        'quote_time': q.get('ts', ''),
        'code': item['code'],
        'name': item['name'],
        'price': q['price'],
        'pct': round(q['pct'], 4),
        'open': q['open'],
        'high': q['high'],
        'low': q['low'],
        'prev_close': q['prev_close'],
        'amount': q['amount'],
        'trigger_price': item['trigger_price'],
        'invalid_price': item['invalid_price'],
    }
    with SNAPSHOTS_CSV_PATH.open('a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def fetch_quotes(watchlist: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    # 新浪行情接口对少量自选股更快、更稳定；字段参考：名称,今开,昨收,现价,最高,最低,...成交量,成交额,日期,时间。
    watchlist = watchlist or WATCHLIST
    symbols = ','.join(market_prefix(item['code']) for item in watchlist)
    resp = requests.get(
        f'https://hq.sinajs.cn/list={symbols}',
        timeout=10,
        headers={'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'},
    )
    resp.raise_for_status()
    text = resp.content.decode('gbk', errors='ignore')
    quotes: dict[str, dict[str, Any]] = {}
    for symbol, payload in re.findall(r'var hq_str_(s[hz]\d{6})="(.*?)";', text):
        parts = payload.split(',')
        if len(parts) < 32 or not parts[0]:
            continue
        code = symbol[2:]
        def num(idx: int) -> float:
            try:
                return float(parts[idx])
            except Exception:
                return 0.0
        price = num(3)
        prev_close = num(2)
        pct = ((price / prev_close - 1) * 100) if prev_close else 0.0
        quotes[code] = {
            'code': code,
            'name': parts[0],
            'price': price,
            'pct': pct,
            'open': num(1),
            'high': num(4),
            'low': num(5),
            'prev_close': prev_close,
            'amount': num(9),
            'volume': num(8),
            'ts': f'{parts[30]} {parts[31]}',
        }
    return quotes



def format_money_yi(amount: float) -> str:
    return f'{amount / 100000000:.2f}亿' if amount else '未知'


def entry_zone(item: dict[str, Any]) -> tuple[float, float]:
    if item.get('zone_low') is not None and item.get('zone_high') is not None:
        return float(item['zone_low']), float(item['zone_high'])
    trigger = float(item['trigger_price'])
    invalid = float(item['invalid_price'])
    # 观察入场区：不追高，优先在观察价下方、且离失效位至少留出空间。
    low = max(invalid * 1.015, trigger * 0.985)
    high = trigger * 1.003
    return low, high


def build_advice(event: str, price: float, trigger: float, invalid: float, q: dict[str, Any]) -> str:
    low, high = max(invalid * 1.015, trigger * 0.985), trigger * 1.003
    if event in {'entry_zone', 'underwater_cross'}:
        return (
            f'观察买入时机：仅在 {low:.2f}–{high:.2f} 区间内观察低吸/小仓试错；'
            f'若跌破 {invalid:.2f} 失效，不补仓；若快速拉离观察价，不追。'
        )
    if event == 'recover_trigger':
        return (
            f'观察买入时机：从水下回收观察价 {trigger:.2f} 后，先看能否站稳；'
            '若回落不破观察价且量价温和，可作为确认型观察点。'
        )
    if event in {'strong_up', 'intraday_fade'}:
        return '观察买入时机：当前不适合追高；等待回落到观察价附近或尾盘确认后再评估。'
    if event in {'invalid', 'near_invalid', 'sharp_down'}:
        return '观察买入时机：暂不考虑；优先看风险是否释放，跌破失效位则从观察池移除。'
    return '观察买入时机：继续观察价格是否回到观察价附近且不破失效位。'


def status_label(event: str) -> str:
    return {
        'entry_zone': '买点区',
        'underwater_cross': '水下观察',
        'underwater': '水下观察',
        'recover_trigger': '回收观察价',
        'strong_up': '强势不追',
        'intraday_fade': '冲高回落',
        'near_invalid': '接近止损',
        'invalid': '跌破止损',
        'sharp_down': '快速走弱',
    }.get(event, '观察')


def format_hhmm(ts: str) -> str:
    try:
        return ts.split()[1][:5]
    except Exception:
        return ts[-8:-3] if ts else ''


EVENT_PRIORITY = {
    'invalid': 0,
    'near_invalid': 1,
    'sharp_down': 2,
    'entry_zone': 3,
    'recover_trigger': 4,
    'strong_up': 5,
    'intraday_fade': 6,
    'underwater_cross': 7,
    'underwater': 8,
}


def build_action(event: str, trigger: float, invalid: float) -> str:
    if event in {'entry_zone', 'underwater', 'underwater_cross'}:
        return f'只等回到买点区/回收{trigger:.2f}；跌破{invalid:.2f}放弃'
    if event == 'recover_trigger':
        return f'看能否站稳{trigger:.2f}；回落不破再观察，跌破{invalid:.2f}放弃'
    if event == 'strong_up':
        return '强势不追；等回踩买点区或尾盘确认'
    if event in {'near_invalid', 'invalid', 'sharp_down'}:
        return f'先放弃买点；跌破{invalid:.2f}移出观察池'
    if event == 'intraday_fade':
        return f'冲高回落先降权；只看能否回收{trigger:.2f}'
    return f'继续观察{trigger:.2f}附近承接；跌破{invalid:.2f}放弃'


def build_alerts(now: datetime, quotes: dict[str, dict[str, Any]], state: dict[str, Any], watchlist: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    watchlist = watchlist or WATCHLIST
    alerts: list[dict[str, Any]] = []
    last_prices: dict[str, float] = state.setdefault('last_prices', {})

    for item in watchlist:
        code = item['code']
        q = quotes.get(code)
        if not q or q['price'] <= 0:
            append_jsonl(EVENTS_JSONL_PATH, {
                'local_time': now.isoformat(timespec='seconds'),
                'event': 'missing_quote',
                'code': code,
                'name': item['name'],
            })
            continue
        append_snapshot(now, item, q)
        price = q['price']
        trigger = item['trigger_price']
        invalid = item['invalid_price']
        zone_low, zone_high = entry_zone(item)
        pct_from_trigger = price / trigger - 1
        pct_from_invalid = price / invalid - 1
        last = float(last_prices.get(code, 0) or 0)
        crossed_under_trigger = last > 0 and last >= trigger and price < trigger
        crossed_over_trigger = last > 0 and last < trigger and price >= trigger
        in_entry_zone = zone_low <= price <= zone_high
        last_prices[code] = price

        candidates: list[tuple[str, str, str]] = []
        if price <= invalid:
            candidates.append(('invalid', '策略失效/风险', f'当前价 {price:.2f} 已跌破失效位 {invalid:.2f}'))
        elif pct_from_invalid <= 0.015:
            candidates.append(('near_invalid', '接近失效位', f'当前价 {price:.2f} 距失效位 {invalid:.2f} 约 {pct_from_invalid*100:.1f}%'))
        if in_entry_zone and pct_from_invalid > 0.015:
            candidates.append(('entry_zone', '观察买入时机', f'当前价 {price:.2f} 处于低吸观察区 {zone_low:.2f}–{zone_high:.2f}'))
        if price < trigger and pct_from_invalid > 0.015:
            event = 'underwater_cross' if crossed_under_trigger else 'underwater'
            candidates.append((event, 'D3水下观察', f'当前价 {price:.2f} 低于观察价 {trigger:.2f}（{pct_from_trigger*100:.1f}%）'))
        if crossed_over_trigger and q['pct'] > 0:
            candidates.append(('recover_trigger', '水下回收观察价', f'从观察价下方回到 {trigger:.2f} 上方，当前 {price:.2f}'))
        if q['pct'] >= 5 and price > trigger:
            candidates.append(('strong_up', '强势拉升', f'当前涨幅 {q["pct"]:.2f}%，已明显高于观察价，注意不追高'))
        if q['pct'] <= -5:
            candidates.append(('sharp_down', '快速走弱', f'当前跌幅 {q["pct"]:.2f}%，需观察是否破位'))
        if q['high'] and q['high'] / max(q['prev_close'], 0.01) - 1 >= 0.07 and price / q['high'] - 1 <= -0.03:
            candidates.append(('intraday_fade', '冲高回落', f'盘中最高 {q["high"]:.2f}，现价 {price:.2f}，高点回落明显'))

        if not candidates:
            append_jsonl(EVENTS_JSONL_PATH, {
                'local_time': now.isoformat(timespec='seconds'),
                'event': 'snapshot_no_alert',
                'code': code,
                'name': item['name'],
                'price': price,
                'pct': q['pct'],
                'trigger_price': trigger,
                'invalid_price': invalid,
                'entry_zone_low': round(zone_low, 4),
                'entry_zone_high': round(zone_high, 4),
                'quote_time': q.get('ts', ''),
            })
            continue

        for ev, title, reason in sorted(candidates, key=lambda c: EVENT_PRIORITY.get(c[0], 99))[:1]:
            record = {
                'local_time': now.isoformat(timespec='seconds'),
                'event': ev,
                'title': title,
                'code': code,
                'name': item['name'],
                'price': price,
                'pct': q['pct'],
                'amount': q['amount'],
                'open': q['open'],
                'high': q['high'],
                'low': q['low'],
                'prev_close': q['prev_close'],
                'trigger_price': trigger,
                'invalid_price': invalid,
                'entry_zone_low': round(zone_low, 4),
                'entry_zone_high': round(zone_high, 4),
                'reason': reason,
                'advice': build_advice(ev, price, trigger, invalid, q),
                'quote_time': q.get('ts', ''),
            }
            append_jsonl(EVENTS_JSONL_PATH, record)
            industry = item.get('industry') or '未知行业'
            hhmm = format_hhmm(q.get('ts', ''))
            stop_distance = price / invalid - 1 if invalid else 0.0
            stage = item.get('stage') or f'{now:%m%d}D3'
            alerts.append({
                'event': ev,
                'stage': stage,
                'code': code,
                'name': item['name'],
                'industry': industry,
                'price': price,
                'pct': q['pct'],
                'zone_low': zone_low,
                'zone_high': zone_high,
                'invalid': invalid,
                'trigger': trigger,
                'stop_distance': stop_distance,
                'amount': q['amount'],
                'hhmm': hhmm,
            })
    return alerts

def format_alert(alert: dict[str, Any]) -> str:
    event = str(alert['event'])
    trigger = float(alert['trigger'])
    invalid = float(alert['invalid'])
    lines = [
        f'{alert["stage"]} | {alert["code"]} {alert["name"]} | {alert["industry"]} | {status_label(event)}',
        f'现价 {float(alert["price"]):.2f} ({float(alert["pct"]):+.2f}%) | 买点 {float(alert["zone_low"]):.2f}–{float(alert["zone_high"]):.2f} | 止损 {invalid:.2f}',
        f'动作：{build_action(event, trigger, invalid)}',
        f'参考：距止损{float(alert["stop_distance"])*100:+.1f}% | 成交额{format_money_yi(float(alert["amount"]))} | {alert["hhmm"]}',
    ]
    return '\n'.join(lines)


def format_alert_summary(alerts: list[dict[str, Any]]) -> str:
    ordered = sorted(alerts, key=lambda a: (EVENT_PRIORITY.get(str(a.get('event')), 99), str(a.get('code'))))
    if len(ordered) == 1:
        return '```text\n' + format_alert(ordered[0]) + '\n```'
    header = f'【A股监控】同轮事件合并 {len(ordered)}只｜{ordered[0].get("hhmm", "")}'
    blocks = [header]
    for i, alert in enumerate(ordered, 1):
        blocks.append(f'{i}. ' + format_alert(alert))
    return '```text\n' + '\n\n'.join(blocks) + '\n```'


def alert_sort_key(alert: dict[str, Any]) -> tuple[int, str]:
    return EVENT_PRIORITY.get(str(alert.get('event')), 99), str(alert.get('code', ''))


def queue_pending_alerts(state: dict[str, Any], alerts: list[dict[str, Any]], now: datetime) -> None:
    if not alerts:
        return
    pending = state.setdefault('pending_alerts', [])
    if not isinstance(pending, list):
        pending = []
        state['pending_alerts'] = pending
    by_code: dict[str, dict[str, Any]] = {
        str(alert.get('code', '')): alert
        for alert in pending
        if isinstance(alert, dict) and alert.get('code')
    }
    for alert in alerts:
        queued = dict(alert)
        queued['queued_at'] = now.isoformat(timespec='seconds')
        code = str(queued.get('code', ''))
        old = by_code.get(code)
        if old is None or alert_sort_key(queued) <= alert_sort_key(old):
            by_code[code] = queued
    state['pending_alerts'] = sorted(by_code.values(), key=alert_sort_key)


def pop_pending_alerts(state: dict[str, Any]) -> list[dict[str, Any]]:
    pending = state.get('pending_alerts')
    state['pending_alerts'] = []
    if not isinstance(pending, list):
        return []
    return sorted([alert for alert in pending if isinstance(alert, dict)], key=alert_sort_key)



def build_monitor_report(now: datetime, quotes: dict[str, dict[str, Any]], watchlist: list[dict[str, Any]] | None = None) -> str:
    watchlist = watchlist or WATCHLIST
    stages = sorted({str(item.get('stage') or f'{now:%m%d}D3') for item in watchlist})
    stage_label = '/'.join(stages) if stages else f'{now:%m%d}D3'
    lines = [
        f'【A股监控】{stage_label}主板{len(watchlist)}股盘中快照',
        f'本地时间：{now:%Y-%m-%d %H:%M:%S}',
        '口径：观察信号，不是确定性交易指令；请结合仓位和风险自行判断。',
        '',
    ]
    for item in watchlist:
        code = item['code']
        q = quotes.get(code)
        trigger = float(item['trigger_price'])
        invalid = float(item['invalid_price'])
        zone_low, zone_high = entry_zone(item)
        if not q or q.get('price', 0) <= 0:
            industry = item.get('industry') or '未知行业'
            stage = item.get('stage') or f'{now:%m%d}D3'
            lines.extend([
                f'{stage} | {code} {item["name"]} | {industry} | 行情缺失',
                f'现价 -- (--%) | 买点 {zone_low:.2f}–{zone_high:.2f} | 止损 {invalid:.2f}',
                f'动作：等待行情恢复；跌破{invalid:.2f}放弃',
                f'参考：距止损-- | 成交额-- | {now:%Y-%m-%d %H:%M:%S}',
                '',
            ])
            continue
        price = float(q['price'])
        stop_distance = price / invalid - 1 if invalid else 0.0
        if price <= invalid:
            event = 'invalid'
        elif zone_low <= price <= zone_high:
            event = 'entry_zone'
        elif price < trigger:
            event = 'underwater'
        elif q['pct'] >= 5 and price > trigger:
            event = 'strong_up'
        else:
            event = 'observe'
        industry = item.get('industry') or '未知行业'
        stage = item.get('stage') or f'{now:%m%d}D3'
        lines.extend([
            f'{stage} | {code} {item["name"]} | {industry} | {status_label(event)}',
            f'现价 {price:.2f} ({q["pct"]:+.2f}%) | 买点 {zone_low:.2f}–{zone_high:.2f} | 止损 {invalid:.2f}',
            f'动作：{build_action(event, trigger, invalid)}',
            f'参考：距止损{stop_distance*100:+.1f}% | 成交额{format_money_yi(q["amount"])} | {now:%Y-%m-%d %H:%M:%S}',
            '',
        ])
    return '```text\n' + '\n'.join(lines).rstrip() + '\n```'


def write_watchlist_csv(watchlist: list[dict[str, Any]] | None = None) -> None:
    path = WATCHLIST_CSV_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    watchlist = watchlist or WATCHLIST
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['code', 'name', 'industry', 'stage', 'pool_type', 'source_file', 'trigger_price', 'invalid_price', 'zone_low', 'zone_high', 'rank', 'score', 'note'])
        writer.writeheader()
        writer.writerows(watchlist)


def main() -> int:
    now = datetime.now()
    watchlist = load_watchlist()
    write_watchlist_csv(watchlist)
    if not validate_watchlist_date(now, watchlist):
        return 0
    if os.getenv('FORCE_RUN') != '1' and not is_trading_window(now):
        return 0
    state = load_state()
    try:
        quotes = fetch_quotes(watchlist)
    except Exception as e:
        append_log(f'[{now:%Y-%m-%d %H:%M:%S}] fetch_error {type(e).__name__}: {e}')
        return 0

    alerts: list[dict[str, Any]] = []
    if should_run_event_check(now):
        alerts = build_alerts(now, quotes, state, watchlist)
        state['last_event_run_at'] = now.isoformat(timespec='seconds')
        queue_pending_alerts(state, alerts, now)
    else:
        append_log(f'[{now:%Y-%m-%d %H:%M:%S}] skipped event_check minute={now.minute}')

    queued_alerts = pop_pending_alerts(state) if should_flush_alerts(now) else []
    if queued_alerts:
        # 15分钟快照点与事件撞车时：快照只落本地，不再排队推送，避免微信/iLink 限流。
        if should_generate_snapshot(now):
            build_monitor_report(now, quotes, watchlist)
            append_log(f'[{now:%Y-%m-%d %H:%M:%S}] wrote local snapshot after queued event(s)')
        state['last_alert_flush_at'] = now.isoformat(timespec='seconds')
        save_state(state)
        ordered = sorted(queued_alerts, key=alert_sort_key)
        visible = ordered[:3]
        dropped = len(ordered) - len(visible)
        lines = []
        for alert in visible:
            if lines:
                lines.append('')
            lines.append(format_alert(alert))
        if dropped > 0:
            lines.extend(['', f'另有 {dropped} 个较低优先级事件已只写入本地日志，避免微信/iLink 限流。'])
        out = '```text\n' + '\n'.join(lines) + '\n```'
        append_log(f'[{now:%Y-%m-%d %H:%M:%S}] sent queued_alert events={len(queued_alerts)} visible={len(visible)} dropped={dropped}')
        print(out)
    else:
        if pending_snapshot_due(now, state):
            pop_pending_snapshot(state)
            save_state(state)
            append_log(f'[{now:%Y-%m-%d %H:%M:%S}] dropped pending_snapshot local_only')
            return 0
        if should_generate_snapshot(now):
            build_monitor_report(now, quotes, watchlist)
            save_state(state)
            append_log(f'[{now:%Y-%m-%d %H:%M:%S}] wrote local snapshot quotes={len(quotes)} pending_alerts={len(state.get("pending_alerts", []))}')
        else:
            save_state(state)
            append_log(f'[{now:%Y-%m-%d %H:%M:%S}] silent minute_check quotes={len(quotes)} new_alerts={len(alerts)} pending_alerts={len(state.get("pending_alerts", []))}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
