#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
WATCHLIST_DIR = PROJECT / 'data/watchlists'
TRADES_PATH = PROJECT / 'data/trades/tulong_trades.csv'
ACTIVE_WATCHLIST = WATCHLIST_DIR / 'tulong_active_watchlist.csv'
LEGACY_ACTIVE_D3 = WATCHLIST_DIR / 'tulong_d3.csv'
STATE_PATH = WATCHLIST_DIR / 'tulong_d3_monitor_state.json'
LOG_PATH = PROJECT / 'reports/alerts/tulong_d3_monitor.log'
VALIDATION_PATH = WATCHLIST_DIR / 'tulong_d3_preopen_validation.json'

MAIN_BOARD_PREFIXES = ('600', '601', '603', '605', '000', '001', '002', '003')
FILTER_PREFIXES = ('300', '301', '688', '689', '8', '4', '9')
ACTIVE_FIELDNAMES = [
    'code', 'name', 'industry', 'stage', 'pool_type', 'source_file',
    'trigger_price', 'invalid_price', 'zone_low', 'zone_high',
    'rank', 'score', 'note',
    'entry_date', 'entry_stage', 'entry_price', 'quantity',
    'sellable_quantity', 'cost_amount',
]
VALID_POOL_TYPES = {'watch', 'position'}


def append_log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(message + '\n')


def label_for(now: datetime, stage: str) -> str:
    if stage == 'HOLD':
        return 'HOLD'
    return f'{now:%m%d}{stage}'


def previous_trading_day(now: datetime) -> datetime:
    prev = now - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def timestamp_score(path: Path) -> tuple[str, float]:
    stem = path.stem
    parts = stem.rsplit('_', 2)
    if len(parts) >= 3 and len(parts[-2]) == 8 and parts[-2].isdigit() and len(parts[-1]) == 6 and parts[-1].isdigit():
        explicit = f'{parts[-2]}_{parts[-1]}'
    else:
        explicit = ''
    return explicit, path.stat().st_mtime


def latest_matching(patterns: list[str]) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(p for p in WATCHLIST_DIR.glob(pattern) if p.name != ACTIVE_WATCHLIST.name)
    timestamped = [p for p in set(matches) if timestamp_score(p)[0]]
    if not timestamped:
        return None
    return sorted(timestamped, key=timestamp_score, reverse=True)[0]


def find_latest_source(now: datetime, stage: str, pool_type: str) -> Path | None:
    label = label_for(now, stage)
    return latest_matching([f'{label}_{pool_type}_*_*.csv'])


def find_sources(now: datetime) -> list[Path]:
    sources: list[Path] = []
    # watch 走当日 MMDDD3；HOLD 持仓从 data/trades/tulong_trades.csv 派生。
    path = find_latest_source(now, 'D3', 'watch')
    if path:
        sources.append(path)
    return sources


def is_main_board(code: str) -> bool:
    code = str(code).zfill(6)
    return code.startswith(MAIN_BOARD_PREFIXES) and not code.startswith(FILTER_PREFIXES)


def infer_stage_pool(src: Path) -> tuple[str, str]:
    parts = src.stem.split('_')
    if len(parts) < 3:
        raise RuntimeError(f'invalid source filename: {src.name}')
    stage = parts[0]
    pool_type = parts[1]
    if pool_type not in VALID_POOL_TYPES:
        raise RuntimeError(f'invalid pool_type in filename: {src.name}')
    return stage, pool_type


def normalize_source_rows(src: Path) -> tuple[list[dict[str, str]], list[str]]:
    fallback_stage, fallback_pool_type = infer_stage_pool(src)
    rows: list[dict[str, str]] = []
    filtered: list[str] = []
    with src.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            code = str(row.get('code', '')).zfill(6)
            if not code or code == '000000':
                continue
            if not is_main_board(code):
                filtered.append(f'{code} {row.get("name", "")}'.strip())
                continue
            stage = row.get('stage') or fallback_stage
            pool_type = row.get('pool_type') or fallback_pool_type
            if pool_type not in VALID_POOL_TYPES:
                raise RuntimeError(f'invalid pool_type={pool_type} code={code} source={src.name}')
            if pool_type == 'position' and str(stage) != 'HOLD':
                raise RuntimeError(f'position rows must use stage=HOLD: code={code} stage={stage} source={src.name}')
            if str(stage) == 'HOLD' and pool_type != 'position':
                raise RuntimeError(f'HOLD only accepts position rows: code={code} pool_type={pool_type} source={src.name}')
            if pool_type == 'watch' and not str(stage).endswith('D3'):
                raise RuntimeError(f'watch rows must use MMDDD3 stage: code={code} stage={stage} source={src.name}')
            out = {name: row.get(name, '') for name in ACTIVE_FIELDNAMES}
            out.update({
                'code': code,
                'name': row.get('name', ''),
                'industry': row.get('industry', ''),
                'stage': stage,
                'pool_type': pool_type,
                'source_file': row.get('source_file') or src.name,
                'trigger_price': row.get('trigger_price', ''),
                'invalid_price': row.get('invalid_price', ''),
                'zone_low': row.get('zone_low', ''),
                'zone_high': row.get('zone_high', ''),
                'rank': row.get('rank') or str(len(rows) + 1),
                'score': row.get('score', ''),
                'note': row.get('note', ''),
                'entry_date': row.get('entry_date', ''),
                'entry_stage': row.get('entry_stage', ''),
                'entry_price': row.get('entry_price', ''),
                'quantity': row.get('quantity', ''),
                'sellable_quantity': row.get('sellable_quantity', ''),
                'cost_amount': row.get('cost_amount', ''),
            })
            if not out['note']:
                out['note'] = f'{stage}｜{pool_type}｜source:{src.name}'
            rows.append(out)
    return rows, filtered


def fmt_price(value: float) -> str:
    return f'{value:.3f}'


def derive_open_positions_from_trades(now: datetime) -> list[dict[str, str]]:
    if not TRADES_PATH.exists():
        return []
    lots_by_code: dict[str, list[dict[str, object]]] = {}
    with TRADES_PATH.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            code = str(row.get('code', '')).zfill(6)
            if not code or code == '000000':
                continue
            action = (row.get('action') or '').strip().lower()
            try:
                quantity = int(float(row.get('quantity') or 0))
                price = float(row.get('price') or 0)
                fee = float(row.get('fee') or 0)
            except ValueError:
                continue
            if quantity <= 0:
                continue
            lots = lots_by_code.setdefault(code, [])
            if action == 'buy':
                lots.append({
                    'quantity': quantity,
                    'price': price,
                    'fee_per_share': fee / quantity if quantity else 0.0,
                    'trade_date': row.get('trade_date') or '',
                    'entry_stage': row.get('position_ref') or row.get('session_label') or '',
                    'name': row.get('name') or code,
                })
            elif action == 'sell':
                remaining = quantity
                while remaining > 0 and lots:
                    lot = lots[0]
                    lot_qty = int(str(lot['quantity']))
                    used = min(lot_qty, remaining)
                    lot['quantity'] = lot_qty - used
                    remaining -= used
                    if int(str(lot['quantity'])) <= 0:
                        lots.pop(0)

    rows: list[dict[str, str]] = []
    for code, lots in sorted(lots_by_code.items()):
        open_lots = [lot for lot in lots if int(str(lot['quantity'])) > 0]
        if not open_lots or not is_main_board(code):
            continue
        quantity = sum(int(str(lot['quantity'])) for lot in open_lots)
        weighted_cost = sum(int(str(lot['quantity'])) * float(str(lot['price'])) for lot in open_lots)
        fee_cost = sum(int(str(lot['quantity'])) * float(str(lot.get('fee_per_share') or 0.0)) for lot in open_lots)
        entry_price = weighted_cost / quantity
        entry_dates = [str(lot.get('trade_date') or '') for lot in open_lots if lot.get('trade_date')]
        entry_date = min(entry_dates) if entry_dates else ''
        entry_stages: list[str] = []
        for lot in open_lots:
            stage = str(lot.get('entry_stage') or '')
            if stage and stage not in entry_stages:
                entry_stages.append(stage)
        name = str(open_lots[-1].get('name') or code)
        sellable_quantity = quantity if entry_date and entry_date < now.strftime('%Y-%m-%d') else 0
        rows.append({
            'code': code,
            'name': name,
            'industry': '',
            'stage': 'HOLD',
            'pool_type': 'position',
            'source_file': str(TRADES_PATH.relative_to(PROJECT)),
            'trigger_price': fmt_price(entry_price),
            'invalid_price': fmt_price(entry_price * 0.92),
            'zone_low': fmt_price(entry_price * 0.985),
            'zone_high': fmt_price(entry_price * 1.003),
            'rank': '',
            'score': '',
            'note': f'HOLD｜from_trades｜entry_stage={"/".join(entry_stages) or "unknown"}｜quantity={quantity}｜entry_price={entry_price:.3f}',
            'entry_date': entry_date,
            'entry_stage': '/'.join(entry_stages),
            'entry_price': fmt_price(entry_price),
            'quantity': str(quantity),
            'sellable_quantity': str(sellable_quantity),
            'cost_amount': f'{weighted_cost + fee_cost:.2f}',
        })
    return rows


def write_active_watchlist(sources: list[Path], now: datetime) -> tuple[int, list[str], list[str], list[str], list[str]]:
    rows: list[dict[str, str]] = []
    filtered: list[str] = []
    source_names: list[str] = []
    for src in sources:
        src_rows, src_filtered = normalize_source_rows(src)
        rows.extend(src_rows)
        filtered.extend(src_filtered)
        source_names.append(src.name)
    trade_position_rows = derive_open_positions_from_trades(now)
    if trade_position_rows:
        metadata_by_code = {row.get('code', ''): row for row in rows}
        position_codes = {row['code'] for row in trade_position_rows}
        deduped_rows = []
        for row in rows:
            if row.get('code') in position_codes and row.get('pool_type') == 'watch':
                filtered.append(f'{row.get("code")} {row.get("name", "")} duplicated_as_HOLD_from_trades'.strip())
                continue
            deduped_rows.append(row)
        rows = deduped_rows
        for position in trade_position_rows:
            source = metadata_by_code.get(position['code'], {})
            for key in ('industry', 'trigger_price', 'invalid_price', 'zone_low', 'zone_high', 'rank', 'score'):
                if source.get(key):
                    position[key] = source[key]
            rows.append(position)
        source_names.append(str(TRADES_PATH.relative_to(PROJECT)))
    if not rows:
        raise RuntimeError('no rows after merging timestamped D3 watch source and trade-derived HOLD positions')

    if ACTIVE_WATCHLIST.exists():
        backup = ACTIVE_WATCHLIST.with_name(f'{ACTIVE_WATCHLIST.stem}.backup_{now:%Y%m%d_%H%M%S}{ACTIVE_WATCHLIST.suffix}')
        shutil.copy2(ACTIVE_WATCHLIST, backup)
    elif LEGACY_ACTIVE_D3.exists():
        backup = LEGACY_ACTIVE_D3.with_name(f'{LEGACY_ACTIVE_D3.stem}.backup_{now:%Y%m%d_%H%M%S}{LEGACY_ACTIVE_D3.suffix}')
        shutil.copy2(LEGACY_ACTIVE_D3, backup)

    with ACTIVE_WATCHLIST.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ACTIVE_FIELDNAMES, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    stages = sorted({row.get('stage', '') for row in rows if row.get('stage')})
    pool_types = sorted({row.get('pool_type', '') for row in rows if row.get('pool_type')})
    return len(rows), filtered, source_names, stages, pool_types


def active_state_matches(now: datetime) -> bool:
    if not STATE_PATH.exists() or not ACTIVE_WATCHLIST.exists():
        return False
    try:
        state = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return False
    expected = now.strftime('%Y-%m-%d')
    expected_prefix = f'{now:%m%d}'
    if state.get('watch_date') != expected:
        return False
    try:
        with ACTIVE_WATCHLIST.open(newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return False
    # 仅要求 watch 行带当日日期前缀；position(HOLD) 行无日期，豁免
    return bool(rows) and all(
        str(row.get('stage', '')).startswith(expected_prefix)
        for row in rows
        if row.get('pool_type') == 'watch'
    )


def validate_active_watchlist(now: datetime) -> dict[str, object]:
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from scripts.tulong.runtime import watchdog

    expected_prefix = f'{now:%m%d}'
    watchlist = watchdog.load_watchlist()
    bad_prefix = [item['code'] for item in watchlist if not is_main_board(item['code'])]
    stale_stage = [item['code'] for item in watchlist if item.get('pool_type') == 'watch' and not str(item.get('stage', '')).startswith(expected_prefix)]
    bad_pool_type = [item['code'] for item in watchlist if item.get('pool_type') not in VALID_POOL_TYPES]
    payload = {
        'validated_at': now.isoformat(timespec='seconds'),
        'expected_prefix': expected_prefix,
        'count': len(watchlist),
        'codes': [item['code'] for item in watchlist],
        'bad_prefix': bad_prefix,
        'stale_stage': stale_stage,
        'bad_pool_type': bad_pool_type,
        'ok': bool(watchlist) and not bad_prefix and not stale_stage and not bad_pool_type,
    }
    VALIDATION_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Rotate active Tulong D3 watchlist and trade-derived HOLD positions before market open.')
    parser.add_argument('--date', help='Override watch date, format YYYY-MM-DD. Useful for dry-run verification.')
    parser.add_argument('--force', action='store_true', help='Rotate even if state already matches today.')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now()
    if args.date:
        base = datetime.strptime(args.date, '%Y-%m-%d')
        now = now.replace(year=base.year, month=base.month, day=base.day)

    if active_state_matches(now) and not args.force:
        append_log(f'[{now:%Y-%m-%d %H:%M:%S}] preopen_rotate skip already_current date={now:%Y-%m-%d}')
        return 0

    sources = find_sources(now)
    if not sources:
        msg = f'【A股监控】开盘前切池失败\n未找到今日 {now:%m%d}D3 watch 的 *_YYYYMMDD_HHMMSS.csv；当前监控池未更新。'
        append_log(f'[{now:%Y-%m-%d %H:%M:%S}] preopen_rotate missing_timestamped_sources date={now:%Y-%m-%d}')
        print(msg)
        return 0

    try:
        count, filtered, source_names, active_stages, active_pool_types = write_active_watchlist(sources, now)
        validation = validate_active_watchlist(now)
        if not validation.get('ok'):
            print(f'【A股监控】开盘前切池后校验异常\n{now:%m%d}｜sources={source_names}\n问题：{json.dumps(validation, ensure_ascii=False)}')
            return 0
    except Exception as e:
        append_log(f'[{now:%Y-%m-%d %H:%M:%S}] preopen_rotate error {type(e).__name__}: {e}')
        print(f'【A股监控】开盘前切池失败\n{type(e).__name__}: {e}')
        return 0

    state = {
        'sent': {},
        'last_prices': {},
        'pending_snapshot': None,
        'last_event_run_at': None,
        'watchlist_source': source_names,
        'watch_date': now.strftime('%Y-%m-%d'),
        'stages': active_stages,
        'pool_types': active_pool_types,
        'updated_at': now.isoformat(timespec='seconds'),
        'filtered_out': filtered,
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    append_log(f'[{now:%Y-%m-%d %H:%M:%S}] preopen_rotate ok sources={source_names} count={count} filtered={len(filtered)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
