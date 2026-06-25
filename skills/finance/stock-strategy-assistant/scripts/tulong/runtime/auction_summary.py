from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from watchdog import entry_zone, fetch_quotes, format_money_yi, load_watchlist, validate_watchlist_date

PROJECT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT / 'reports/alerts'


def pct_text(value: float) -> str:
    return f'{value:+.2f}%'


def row_stage(item: dict[str, Any]) -> str:
    if item.get('pool_type') == 'position' or item.get('stage') == 'HOLD':
        return 'HOLD'
    return str(item.get('stage') or 'D3')


def classify_status(item: dict[str, Any], quote: dict[str, Any]) -> str:
    price = float(quote.get('price') or 0)
    trigger = float(item.get('trigger_price') or 0)
    invalid = float(item.get('invalid_price') or 0)
    zone_low, zone_high = entry_zone(item)
    is_position = item.get('pool_type') == 'position' or item.get('stage') == 'HOLD'
    entry_price = float(item.get('entry_price') or trigger or 0)

    if price <= 0:
        return '无有效报价'
    if invalid and price <= invalid:
        return '跌破失效/止损'
    if is_position and entry_price:
        if price < entry_price:
            return '低于成本线'
        if quote.get('pct', 0) >= 3:
            return 'HOLD偏强'
        return 'HOLD观察'
    if zone_low <= price <= zone_high:
        return '进入买点区'
    if trigger and price >= trigger:
        if quote.get('pct', 0) >= 5:
            return '强势不追'
        return '站上观察价'
    return '低于观察价'


def build_rows(now: datetime, watchlist: list[dict[str, Any]], quotes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in watchlist:
        code = str(item.get('code', '')).zfill(6)
        quote = quotes.get(code, {})
        price = float(quote.get('price') or 0)
        trigger = float(item.get('trigger_price') or 0)
        invalid = float(item.get('invalid_price') or 0)
        zone_low, zone_high = entry_zone(item)
        rows.append({
            'local_time': now.isoformat(timespec='seconds'),
            'quote_time': quote.get('ts', ''),
            'code': code,
            'name': item.get('name') or quote.get('name') or code,
            'stage': row_stage(item),
            'pool_type': item.get('pool_type') or '',
            'industry': item.get('industry') or '未分类',
            'price': price,
            'pct': round(float(quote.get('pct') or 0), 4),
            'open': float(quote.get('open') or 0),
            'prev_close': float(quote.get('prev_close') or 0),
            'amount': float(quote.get('amount') or 0),
            'trigger_price': trigger,
            'zone_low': zone_low,
            'zone_high': zone_high,
            'invalid_price': invalid,
            'status': classify_status(item, quote),
        })
    rows.sort(key=lambda r: (r['industry'], -r['pct'], r['code']))
    return rows


def write_csv(now: datetime, rows: list[dict[str, Any]]) -> Path:
    path = OUTPUT_DIR / f'tulong_auction_summary_{now:%Y%m%d}.csv'
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def industry_summary(rows: list[dict[str, Any]]) -> list[tuple[str, int, float, float, int, str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row['industry']].append(row)
    result = []
    for industry, items in grouped.items():
        count = len(items)
        avg_pct = sum(float(x['pct']) for x in items) / count
        amount = sum(float(x['amount']) for x in items)
        strong_count = sum(1 for x in items if float(x['pct']) >= 2)
        leader = max(items, key=lambda x: float(x['pct']))
        leader_text = f"{leader['name']} {pct_text(float(leader['pct']))}"
        result.append((industry, count, avg_pct, amount, strong_count, leader_text))
    result.sort(key=lambda x: (x[4], x[2], x[3]), reverse=True)
    return result


def format_report(now: datetime, rows: list[dict[str, Any]], csv_path: Path) -> str:
    watch_rows = [r for r in rows if r['pool_type'] == 'watch']
    hold_rows = [r for r in rows if r['stage'] == 'HOLD' or r['pool_type'] == 'position']
    valid_rows = [r for r in rows if r['price'] > 0]
    strong_rows = [r for r in valid_rows if r['pct'] >= 2]
    weak_rows = [r for r in valid_rows if r['pct'] <= -2]

    lines = [
        f'【集合竞价汇总】{now:%m%d} {now:%H:%M}',
        f'范围：D3 active {len(watch_rows)} 只 / HOLD {len(hold_rows)} 只 / 有效报价 {len(valid_rows)} 只',
        '',
        '行业/板块强弱：',
    ]
    for industry, count, avg_pct, amount, strong_count, leader in industry_summary(valid_rows)[:8]:
        lines.append(f'- {industry}｜{count}只｜均涨{pct_text(avg_pct)}｜强势{strong_count}只｜竞价额{format_money_yi(amount)}｜领涨 {leader}')

    if strong_rows:
        lines.extend(['', '偏强个股：'])
        for row in sorted(strong_rows, key=lambda x: x['pct'], reverse=True)[:8]:
            lines.append(f"- {row['code']} {row['name']}｜{row['industry']}｜{pct_text(row['pct'])}｜{row['status']}｜额{format_money_yi(row['amount'])}")

    if weak_rows:
        lines.extend(['', '偏弱/风险：'])
        for row in sorted(weak_rows, key=lambda x: x['pct'])[:8]:
            lines.append(f"- {row['code']} {row['name']}｜{row['industry']}｜{pct_text(row['pct'])}｜{row['status']}｜失效{row['invalid_price']:.2f}")

    lines.extend([
        '',
        '口径：集合竞价结果以 09:25 附近新浪行情快照近似，不含未匹配量/委托队列；09:30–10:00 承接仍需二次确认。',
        f'本地明细：{csv_path}',
    ])
    return '\n'.join(lines)


def main() -> None:
    now = datetime.now()
    watchlist = load_watchlist()
    if not validate_watchlist_date(now, watchlist):
        return
    quotes = fetch_quotes(watchlist)
    rows = build_rows(now, watchlist, quotes)
    if not rows:
        print('【集合竞价汇总】无监控标的，未生成行业汇总')
        return
    csv_path = write_csv(now, rows)
    print(format_report(now, rows, csv_path))


if __name__ == '__main__':
    main()
