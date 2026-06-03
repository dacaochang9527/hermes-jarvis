#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[3]
WATCHLIST_DIR = PROJECT / 'data/watchlists'
ACTIVE_WATCHLIST = WATCHLIST_DIR / 'tulong_active_watchlist.csv'
STATE_PATH = WATCHLIST_DIR / 'tulong_d3_monitor_state.json'
LOG_PATH = PROJECT / 'reports/alerts/tulong_d3_monitor.log'

MAIN_BOARD_PREFIXES = ('600', '601', '603', '605', '000', '001', '002', '003')
FILTER_PREFIXES = ('300', '301', '688', '689', '8', '4', '9')
VALID_POOL_TYPES = {'watch', 'position'}
REQUIRED_COMMON = ('industry', 'stage', 'pool_type', 'source_file', 'trigger_price', 'invalid_price', 'zone_low', 'zone_high')
REQUIRED_POSITION = ('entry_date', 'entry_stage', 'entry_price', 'quantity', 'sellable_quantity')


def append_log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(message + '\n')


def is_main_board(code: str) -> bool:
    code = str(code).zfill(6)
    return code.startswith(MAIN_BOARD_PREFIXES) and not code.startswith(FILTER_PREFIXES)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except Exception as e:
        return {'_load_error': f'{type(e).__name__}: {e}'}


def load_active_rows() -> list[dict[str, str]]:
    if not ACTIVE_WATCHLIST.exists():
        return []
    with ACTIVE_WATCHLIST.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def script_load_watchlist_summary() -> dict[str, Any]:
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from scripts.tulong.runtime import watchdog

    watchlist = watchdog.load_watchlist()
    return {
        'count': len(watchlist),
        'codes': [item['code'] for item in watchlist],
        'stages': sorted({item.get('stage', '') for item in watchlist}),
        'pool_types': sorted({item.get('pool_type', '') for item in watchlist}),
        'missing_zone': [item['code'] for item in watchlist if item.get('zone_low') is None or item.get('zone_high') is None],
    }


def validate(now: datetime) -> tuple[list[str], dict[str, Any]]:
    expected_date = now.strftime('%Y-%m-%d')
    expected_prefix = f'{now:%m%d}'

    errors: list[str] = []
    warnings: list[str] = []
    state = load_state()
    rows = load_active_rows()

    if state.get('_load_error'):
        errors.append(f'状态文件读取失败：{state["_load_error"]}')
    if not ACTIVE_WATCHLIST.exists():
        errors.append(f'实际监控池不存在：{ACTIVE_WATCHLIST}')
    if not rows:
        errors.append('实际监控池为空或无法读取')

    if state.get('watch_date') != expected_date:
        errors.append(f'watch_date异常：当前={state.get("watch_date")}，期望={expected_date}')

    bad_prefix = []
    missing_required = []
    for row in rows:
        code = str(row.get('code', '')).zfill(6)
        stage = row.get('stage', '')
        pool_type = row.get('pool_type', '')
        if not is_main_board(code):
            bad_prefix.append(f'{code} {row.get("name", "")}'.strip())
        missing = [key for key in REQUIRED_COMMON if not row.get(key)]
        if pool_type == 'position':
            missing.extend(key for key in REQUIRED_POSITION if not row.get(key))
        if missing:
            missing_required.append(f'{code}:{"/".join(missing)}')
        if pool_type == 'watch' and not stage.startswith(expected_prefix):
            errors.append(f'{code} watch stage日期异常：当前={stage}，期望前缀={expected_prefix}')
        if pool_type not in VALID_POOL_TYPES:
            errors.append(f'{code} pool_type异常：当前={pool_type}，期望=watch/position')
        if pool_type == 'position' and stage != 'HOLD':
            errors.append(f'{code} 持仓行stage应为HOLD，当前={stage}')
        if stage == 'HOLD' and pool_type != 'position':
            errors.append(f'{code} HOLD只允许持仓position，当前pool_type={pool_type}')

    if bad_prefix:
        errors.append('实际监控池混入非沪深主板/20cm标的：' + '、'.join(bad_prefix))
    if missing_required:
        errors.append('实际监控池缺少关键字段：' + '、'.join(missing_required[:8]))

    try:
        loaded = script_load_watchlist_summary()
    except Exception as e:
        errors.append(f'load_watchlist()脚本级验证失败：{type(e).__name__}: {e}')
        loaded = {}
    else:
        csv_codes = [str(row.get('code', '')).zfill(6) for row in rows]
        if loaded.get('codes') != csv_codes:
            errors.append(f'load_watchlist()读取结果与CSV不一致：loaded={loaded.get("codes")} csv={csv_codes}')
        if loaded.get('missing_zone'):
            warnings.append('load_watchlist()存在缺失买点区字段：' + '、'.join(loaded['missing_zone']))

    detail = {
        'checked_at': now.isoformat(timespec='seconds'),
        'expected_prefix': expected_prefix,
        'watchlist_source': state.get('watchlist_source'),
        'row_count': len(rows),
        'codes': [str(row.get('code', '')).zfill(6) for row in rows],
        'stages': sorted({row.get('stage', '') for row in rows}),
        'pool_types': sorted({row.get('pool_type', '') for row in rows}),
        'state_updated_at': state.get('updated_at'),
        'warnings': warnings,
    }
    return errors, detail


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Guard-check active Tulong D3 watchlist and HOLD positions after preopen rotation.')
    parser.add_argument('--date', help='Override watch date, format YYYY-MM-DD. Useful for dry-run verification.')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now()
    if args.date:
        base = datetime.strptime(args.date, '%Y-%m-%d')
        now = now.replace(year=base.year, month=base.month, day=base.day)

    errors, detail = validate(now)
    append_log(f'[{now:%Y-%m-%d %H:%M:%S}] preopen_guard checked errors={len(errors)} warnings={len(detail.get("warnings", []))} prefix={detail.get("expected_prefix")}')

    if errors:
        lines = [
            '【A股监控】09:05守门校验失败：监控池未确认，需暂停旧池风险',
            f'检查时间：{now:%Y-%m-%d %H:%M:%S}',
            f'期望：{detail["expected_prefix"]}D3(watch) / HOLD(position)',
            '',
            '问题：',
        ]
        lines.extend(f'- {e}' for e in errors)
        if detail.get('warnings'):
            lines.extend(['', '提示：', *[f'- {w}' for w in detail['warnings']]])
        lines.extend([
            '',
            f'当前source：{detail.get("watchlist_source")}',
            f'当前stage：{", ".join(detail.get("stages", [])) or "空"}',
            f'当前pool_type：{", ".join(detail.get("pool_types", [])) or "空"}',
            f'当前代码：{", ".join(detail.get("codes", [])) or "空"}',
        ])
        print('\n'.join(lines))
        return 0

    if detail.get('warnings'):
        append_log(f'[{now:%Y-%m-%d %H:%M:%S}] preopen_guard warnings {json.dumps(detail["warnings"], ensure_ascii=False)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
