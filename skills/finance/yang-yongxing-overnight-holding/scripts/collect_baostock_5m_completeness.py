#!/usr/bin/env python3
"""轻量补采 Baostock 5 分钟时间戳，生成 14:30 精确完整性证据。"""

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import datetime as dt
import json
import pathlib
import socket
import time
from collections import defaultdict

import baostock as bs
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
EXPECTED_5M_TIMES_1430 = tuple(time for time in EXPECTED_5M_TIMES if time <= "1430")
socket.setdefaulttimeout(NETWORK_TIMEOUT_SECONDS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", required=True, help="股票代码 JSON 数组")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="冒烟测试代码数；0表示全部")
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
        return {"completed_codes": [], "failures": [], "parts": []}
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


def query_timestamps(code: str, start: str, end: str) -> list[list[str]]:
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = bs.query_history_k_data_plus(
                code,
                "date,time,code",
                start_date=start,
                end_date=end,
                frequency="5",
                adjustflag="3",
            )
            rows: list[list[str]] = []
            while result.error_code == "0" and result.next():
                rows.append(result.get_row_data())
            if result.error_code != "0":
                raise RuntimeError(f"{result.error_code} {result.error_msg}")
            return rows
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(0.5 * attempt)
                reconnect()
    raise RuntimeError(last_error)


def completeness_rows(code: str, source_rows: list[list[str]]) -> list[dict]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for date, timestamp, returned_code in source_rows:
        if returned_code != code:
            raise RuntimeError(f"返回代码不一致：expected={code} actual={returned_code}")
        if not timestamp.startswith(date.replace("-", "")) or len(timestamp) < 12:
            raise RuntimeError(f"非法时间戳：{date} {timestamp}")
        grouped[date].append(timestamp[8:12])

    expected_set = set(EXPECTED_5M_TIMES)
    expected1430_set = set(EXPECTED_5M_TIMES_1430)
    output: list[dict] = []
    for date, source_times in sorted(grouped.items()):
        out_of_order_count = sum(
            current < previous
            for previous, current in zip(source_times, source_times[1:])
        )
        source_times1430 = [value for value in source_times if value <= "1430"]
        out_of_order_count1430 = sum(
            current < previous
            for previous, current in zip(source_times1430, source_times1430[1:])
        )
        times = sorted(source_times)
        times1430 = [value for value in times if value <= "1430"]
        time_set = set(times)
        time1430_set = set(times1430)
        duplicate_count = len(times) - len(time_set)
        duplicate_count1430 = len(times1430) - len(time1430_set)
        unexpected_count = len(time_set - expected_set)
        unexpected_count1430 = len(time1430_set - expected1430_set)
        missing_count = len(expected_set - time_set)
        missing_count1430 = len(expected1430_set - time1430_set)
        has_1430 = times.count("1430") == 1
        output.append(
            {
                "code": code,
                "date": date,
                "bar_count": len(times),
                "distinct_bar_count": len(time_set),
                "duplicate_bar_count": duplicate_count,
                "unexpected_bar_count": unexpected_count,
                "missing_expected_bar_count": missing_count,
                "source_out_of_order_count": out_of_order_count,
                "source_out_of_order_count1430": out_of_order_count1430,
                "first_bar_time": times[0] if times else "",
                "last_bar_time": times[-1] if times else "",
                "bar_count1430": len(times1430),
                "distinct_bar_count1430": len(time1430_set),
                "duplicate_bar_count1430": duplicate_count1430,
                "unexpected_bar_count1430": unexpected_count1430,
                "missing_expected_bar_count1430": missing_count1430,
                "has_1430_bar": has_1430,
                "exact_1430_complete": (
                    len(times1430) == len(EXPECTED_5M_TIMES_1430)
                    and len(time1430_set) == len(EXPECTED_5M_TIMES_1430)
                    and duplicate_count1430 == 0
                    and unexpected_count1430 == 0
                    and missing_count1430 == 0
                    and has_1430
                    and out_of_order_count1430 == 0
                ),
            }
        )
    return output


def collect_code(task: tuple[str, str, str]) -> tuple[str, list[dict]]:
    code, start, end = task
    return code, completeness_rows(code, query_timestamps(code, start, end))


def main() -> None:
    args = parse_args()
    if args.workers < 1 or args.workers > 4:
        raise SystemExit("--workers 必须在1到4之间")
    if args.chunk_size < args.workers:
        raise SystemExit("--chunk-size 不能小于 --workers")
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if start > end:
        raise SystemExit("--start 不能晚于 --end")

    source_codes = json.loads(
        pathlib.Path(args.codes).expanduser().resolve().read_text(encoding="utf-8")
    )
    if not isinstance(source_codes, list) or not all(
        isinstance(code, str) for code in source_codes
    ):
        raise SystemExit("--codes 必须是字符串数组")

    output = pathlib.Path(args.output).expanduser().resolve()
    state_path = output / "state.json"
    if output.exists() and not args.resume:
        raise SystemExit(f"输出目录已存在；若要继续请使用 --resume：{output}")
    output.mkdir(parents=True, exist_ok=True)
    parts_dir = output / "completeness"
    parts_dir.mkdir(exist_ok=True)
    codes_snapshot = output / "codes.json"
    if codes_snapshot.exists():
        codes = json.loads(codes_snapshot.read_text(encoding="utf-8"))
    else:
        codes = source_codes[: args.limit] if args.limit else source_codes
        save_json(codes_snapshot, codes)

    state = load_state(state_path)
    completed = set(state.get("completed_codes", []))
    pending = [code for code in codes if code not in completed]
    started = time.time()
    print(
        f"CODES total={len(codes)} completed={len(completed)} pending={len(pending)}",
        flush=True,
    )

    executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=args.workers, initializer=login_worker
    )
    try:
        for offset in range(0, len(pending), args.chunk_size):
            chunk = pending[offset : offset + args.chunk_size]
            futures = {
                executor.submit(collect_code, (code, args.start, args.end)): code
                for code in chunk
            }
            successful: list[str] = []
            failures: list[dict] = []
            rows: list[dict] = []
            for future in concurrent.futures.as_completed(futures):
                code = futures[future]
                try:
                    returned_code, code_rows = future.result()
                    if returned_code != code:
                        raise RuntimeError(
                            f"任务代码不一致：expected={code} actual={returned_code}"
                        )
                    rows.extend(code_rows)
                    successful.append(code)
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        {"code": code, "error": f"{type(exc).__name__}: {exc}"}
                    )

            if rows:
                part_index = len(state.get("parts", []))
                part_path = parts_dir / f"part-{part_index:05d}.parquet"
                write_table(rows, part_path)
                state.setdefault("parts", []).append(
                    {
                        "path": str(part_path),
                        "codes": sorted(successful),
                        "rows": len(rows),
                    }
                )
            state.setdefault("completed_codes", []).extend(sorted(successful))
            state.setdefault("failures", []).extend(failures)
            state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            state["parameters"] = vars(args)
            state["elapsed_seconds_this_run"] = round(time.time() - started, 3)
            save_json(state_path, state)
            print(
                f"CHUNK completed={len(successful)} failed={len(failures)} "
                f"total_completed={len(set(state['completed_codes']))}",
                flush=True,
            )
    finally:
        executor.shutdown(wait=True, cancel_futures=False)

    completed = set(state.get("completed_codes", []))
    unresolved = sorted(
        {item["code"] for item in state.get("failures", [])} - completed
    )
    print(
        "RESULT="
        + json.dumps(
            {
                "total_codes": len(codes),
                "completed_codes": len(completed),
                "unresolved_failures": len(unresolved),
                "elapsed_seconds_this_run": state["elapsed_seconds_this_run"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
