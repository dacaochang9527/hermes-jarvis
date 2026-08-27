#!/usr/bin/env python3
"""补采次日退出门禁所需的少量 5 分钟窗口和日线字段。

全年绝大多数股票日已经有完整 48 根 K 线证据。本脚本只补采三类日期：
年度边界的 2025-01-02、原完整性记录缺失/异常的次日、以及早盘成交均价恰好
落在跌停价但日内后来打开的日期。输出可恢复，不覆盖已完成分片。
"""

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import datetime as dt
import json
import math
import pathlib
import socket
import time
from collections import Counter

import baostock as bs
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


NETWORK_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
EXPECTED_5M_TIMES = tuple(
    [f"09{minute:02d}" for minute in range(35, 60, 5)]
    + [f"10{minute:02d}" for minute in range(0, 60, 5)]
    + [f"11{minute:02d}" for minute in range(0, 31, 5)]
    + [f"13{minute:02d}" for minute in range(5, 60, 5)]
    + [f"14{minute:02d}" for minute in range(0, 60, 5)]
    + ["1500"]
)
EXPECTED_EXIT_TIMES = ("0935", "0940", "0945", "0950", "0955", "1000")
socket.setdefaulttimeout(NETWORK_TIMEOUT_SECONDS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audited-input", required=True)
    parser.add_argument("--completeness", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk-size", type=int, default=40)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def save_json(path: pathlib.Path, value: dict | list) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def write_table(rows: list[dict], path: pathlib.Path) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"completed_targets": [], "failures": [], "parts": []}
    return json.loads(path.read_text(encoding="utf-8"))


def login_worker() -> None:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login: {login.error_code} {login.error_msg}")
    atexit.register(bs.logout)


def reconnect() -> None:
    try:
        bs.logout()
    except Exception:  # noqa: BLE001
        pass
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock relogin: {login.error_code} {login.error_msg}")


def as_float(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else math.nan
    except (TypeError, ValueError):
        return math.nan


def query_rows(code: str, date: str, frequency: str, fields: str) -> list[dict]:
    last_error = ""
    names = fields.split(",")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = bs.query_history_k_data_plus(
                code,
                fields,
                start_date=date,
                end_date=date,
                frequency=frequency,
                adjustflag="3",
            )
            rows: list[dict] = []
            while result.error_code == "0" and result.next():
                rows.append(dict(zip(names, result.get_row_data())))
            if result.error_code != "0":
                raise RuntimeError(f"{result.error_code} {result.error_msg}")
            return rows
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(0.5 * attempt)
                reconnect()
    raise RuntimeError(last_error)


def exact_times(source_times: list[str], expected: tuple[str, ...]) -> bool:
    expected_set = set(expected)
    return (
        len(source_times) == len(expected)
        and len(set(source_times)) == len(expected)
        and set(source_times) == expected_set
        and sum(
            current < previous
            for previous, current in zip(source_times, source_times[1:])
        )
        == 0
    )


def aggregate_target(target: dict) -> dict:
    code = target["code"]
    date = target["date"]
    daily_rows = query_rows(
        code,
        date,
        "d",
        "date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,isST",
    )
    bars = query_rows(
        code,
        date,
        "5",
        "date,time,code,open,high,low,close,volume,amount,adjustflag",
    )
    daily = daily_rows[0] if daily_rows else {}
    source_times = [row["time"][8:12] for row in bars]
    ordered_bars = sorted(bars, key=lambda row: row["time"])
    early_bars = [row for row in ordered_bars if row["time"][8:12] <= "1000"]
    first_bars = [row for row in ordered_bars if row["time"][8:12] == "0935"]
    bars1430 = [row for row in ordered_bars if row["time"][8:12] <= "1430"]

    def aggregate(selected: list[dict]) -> dict:
        volume = sum(
            value if math.isfinite(value := as_float(row["volume"])) else 0.0
            for row in selected
        )
        amount = sum(
            value if math.isfinite(value := as_float(row["amount"])) else 0.0
            for row in selected
        )
        lows = [as_float(row["low"]) for row in selected]
        highs = [as_float(row["high"]) for row in selected]
        lows = [value for value in lows if math.isfinite(value)]
        highs = [value for value in highs if math.isfinite(value)]
        return {
            "volume": volume,
            "amount": amount,
            "vwap": amount / volume if volume > 0 else math.nan,
            "low": min(lows) if lows else math.nan,
            "high": max(highs) if highs else math.nan,
        }

    first = aggregate(first_bars)
    early = aggregate(early_bars)
    through1430 = aggregate(bars1430)
    full = aggregate(ordered_bars)
    daily_volume = as_float(daily.get("volume"))
    daily_amount = as_float(daily.get("amount"))
    daily_turnover = as_float(daily.get("turn"))
    early_times = [row["time"][8:12] for row in bars if row["time"][8:12] <= "1000"]
    full_counter = Counter(source_times)
    expected_full_set = set(EXPECTED_5M_TIMES)
    exact_full = (
        exact_times(source_times, EXPECTED_5M_TIMES)
        and not set(source_times) - expected_full_set
        and all(full_counter[value] == 1 for value in EXPECTED_5M_TIMES)
    )
    return {
        **target,
        "daily_row_present": bool(daily_rows),
        "daily_open": as_float(daily.get("open")),
        "daily_high": as_float(daily.get("high")),
        "daily_low": as_float(daily.get("low")),
        "daily_close": as_float(daily.get("close")),
        "daily_preclose": as_float(daily.get("preclose")),
        "daily_volume": daily_volume,
        "daily_amount": daily_amount,
        "daily_turnover": daily_turnover,
        "daily_trade_status": int(daily.get("tradestatus") or 0),
        "daily_is_st": daily.get("isST") == "1",
        "bar_count": len(bars),
        "distinct_bar_count": len(set(source_times)),
        "source_out_of_order_count": sum(
            current < previous
            for previous, current in zip(source_times, source_times[1:])
        ),
        "exact_full_complete": exact_full,
        "early_bar_count": len(early_bars),
        "early_distinct_bar_count": len(set(early_times)),
        "early_missing_times": sorted(set(EXPECTED_EXIT_TIMES) - set(early_times)),
        "early_duplicate_count": len(early_times) - len(set(early_times)),
        "early_unexpected_times": sorted(set(early_times) - set(EXPECTED_EXIT_TIMES)),
        "exact_exit_window_complete": exact_times(early_times, EXPECTED_EXIT_TIMES),
        "first_5m_volume": first["volume"],
        "first_5m_amount": first["amount"],
        "first_5m_vwap": first["vwap"],
        "first_5m_low": first["low"],
        "first_5m_high": first["high"],
        "to_1000_volume": early["volume"],
        "to_1000_amount": early["amount"],
        "to_1000_vwap": early["vwap"],
        "to_1000_low": early["low"],
        "to_1000_high": early["high"],
        "cum_volume1430": through1430["volume"],
        "cum_amount1430": through1430["amount"],
        "full_5m_volume": full["volume"],
        "full_5m_amount": full["amount"],
        "minute_exceeds_daily_volume": (
            math.isfinite(daily_volume)
            and through1430["volume"] > daily_volume + 1.0
        ),
        "full_minute_exceeds_daily_volume": (
            math.isfinite(daily_volume) and full["volume"] > daily_volume + 1.0
        ),
    }


def collect_target(target: dict) -> tuple[str, dict]:
    key = f"{target['code']}|{target['date']}"
    return key, aggregate_target(target)


def build_targets(
    audited_input: pathlib.Path, completeness_glob: str
) -> list[dict]:
    connection = duckdb.connect()
    query = """
    WITH next_rows AS (
      SELECT code,date,preclose,is_st,high_bfq
      FROM read_parquet(?)
    ), joined AS (
      SELECT a.code,a.next_market_date AS date,
        a.next_market_date='2025-01-02' AS reason_boundary_date,
        NOT coalesce(
          c.bar_count=48 AND c.distinct_bar_count=48
          AND c.duplicate_bar_count=0 AND c.unexpected_bar_count=0
          AND c.missing_expected_bar_count=0
          AND c.source_out_of_order_count=0,false
        ) AS reason_existing_completeness_not_exact,
        CASE WHEN isfinite(n.preclose) AND n.preclose>0
             THEN floor(n.preclose*(CASE WHEN n.is_st THEN 0.95 ELSE 0.90 END)
                        *100.0+0.5)/100.0 END AS lower_limit,
        a.raw_next_exit_first_5m_vwap,
        a.raw_next_exit_to_1000_vwap,
        n.high_bfq
      FROM read_parquet(?) a
      LEFT JOIN read_parquet(?) c
        ON c.code=a.code AND c.date=a.next_market_date
      LEFT JOIN next_rows n
        ON n.code=a.code AND n.date=a.next_market_date
      WHERE a.next_market_date IS NOT NULL
    ), reasons AS (
      SELECT *,
        coalesce(
          high_bfq>lower_limit+0.0005
          AND (
            abs(raw_next_exit_first_5m_vwap-lower_limit)<=0.0005
            OR abs(raw_next_exit_to_1000_vwap-lower_limit)<=0.0005
          ),false
        ) AS reason_limit_queue_needs_early_high
      FROM joined
    )
    SELECT code,date,
      bool_or(reason_boundary_date) AS reason_boundary_date,
      bool_or(reason_existing_completeness_not_exact)
        AS reason_existing_completeness_not_exact,
      bool_or(reason_limit_queue_needs_early_high)
        AS reason_limit_queue_needs_early_high
    FROM reasons
    GROUP BY code,date
    HAVING bool_or(reason_boundary_date)
        OR bool_or(reason_existing_completeness_not_exact)
        OR bool_or(reason_limit_queue_needs_early_high)
    ORDER BY code,date
    """
    cursor = connection.execute(
        query,
        [str(audited_input), str(audited_input), completeness_glob],
    )
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def main() -> None:
    args = parse_args()
    if args.workers < 1 or args.workers > 4:
        raise SystemExit("--workers 必须在1到4之间")
    if args.chunk_size < args.workers:
        raise SystemExit("--chunk-size 不能小于 --workers")
    audited_input = pathlib.Path(args.audited_input).expanduser().resolve()
    completeness = pathlib.Path(args.completeness).expanduser().resolve()
    output = pathlib.Path(args.output).expanduser().resolve()
    state_path = output / "state.json"
    if output.exists() and not args.resume:
        raise SystemExit(f"输出目录已存在；若要继续请使用 --resume：{output}")
    if not audited_input.is_file():
        raise SystemExit(f"审计输入不存在：{audited_input}")
    if not completeness.is_dir():
        raise SystemExit(f"完整性目录不存在：{completeness}")

    output.mkdir(parents=True, exist_ok=True)
    parts_dir = output / "supplement"
    parts_dir.mkdir(exist_ok=True)
    targets_path = output / "targets.json"
    if targets_path.exists():
        targets = json.loads(targets_path.read_text(encoding="utf-8"))
    else:
        targets = build_targets(audited_input, str(completeness / "*.parquet"))
        save_json(targets_path, targets)

    state = load_state(state_path)
    completed = set(state.get("completed_targets", []))
    pending = [
        target
        for target in targets
        if f"{target['code']}|{target['date']}" not in completed
    ]
    started = time.time()
    print(
        f"TARGETS total={len(targets)} completed={len(completed)} pending={len(pending)}",
        flush=True,
    )

    executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=args.workers, initializer=login_worker
    )
    try:
        for offset in range(0, len(pending), args.chunk_size):
            chunk = pending[offset : offset + args.chunk_size]
            futures = {
                executor.submit(collect_target, target): target for target in chunk
            }
            rows: list[dict] = []
            successful: list[str] = []
            failures: list[dict] = []
            for future in concurrent.futures.as_completed(futures):
                target = futures[future]
                key = f"{target['code']}|{target['date']}"
                try:
                    returned_key, row = future.result()
                    if returned_key != key:
                        raise RuntimeError(
                            f"目标不一致：expected={key} actual={returned_key}"
                        )
                    rows.append(row)
                    successful.append(key)
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        {"target": key, "error": f"{type(exc).__name__}: {exc}"}
                    )
            if rows:
                part_index = len(state.get("parts", []))
                part_path = parts_dir / f"part-{part_index:05d}.parquet"
                write_table(rows, part_path)
                state.setdefault("parts", []).append(
                    {
                        "path": str(part_path),
                        "targets": sorted(successful),
                        "rows": len(rows),
                    }
                )
            completed.update(successful)
            prior_failures = {
                item["target"]: item for item in state.get("failures", [])
            }
            for item in failures:
                prior_failures[item["target"]] = item
            for key in successful:
                prior_failures.pop(key, None)
            state["completed_targets"] = sorted(completed)
            state["failures"] = sorted(
                prior_failures.values(), key=lambda item: item["target"]
            )
            state["parameters"] = {
                "audited_input": str(audited_input),
                "completeness": str(completeness),
                "output": str(output),
                "workers": args.workers,
                "chunk_size": args.chunk_size,
            }
            state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            state["elapsed_seconds_this_run"] = round(time.time() - started, 3)
            save_json(state_path, state)
            print(
                f"CHUNK completed={len(successful)} failed={len(failures)} "
                f"total_completed={len(completed)}/{len(targets)}",
                flush=True,
            )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    unresolved = state.get("failures", [])
    remaining = len(targets) - len(completed)
    print(
        f"DONE completed={len(completed)} remaining={remaining} "
        f"unresolved_failures={len(unresolved)} elapsed={time.time()-started:.1f}s",
        flush=True,
    )
    if remaining or unresolved:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
