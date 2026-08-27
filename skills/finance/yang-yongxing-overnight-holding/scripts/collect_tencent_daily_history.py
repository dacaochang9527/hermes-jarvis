#!/usr/bin/env python3
"""并发采集腾讯不复权历史日线，并使用 Baostock 生成交易日历。

用于修复 2024 年五分钟聚合数据中未落盘的历史日线窗口。采集可恢复，
不会覆盖已存在的输出目录；失败代码在 --resume 时自动重试。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import pathlib
import socket
import time
import urllib.parse
import urllib.request

import baostock as bs
import pyarrow as pa
import pyarrow.parquet as pq


TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
NETWORK_TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3
socket.setdefaulttimeout(NETWORK_TIMEOUT_SECONDS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", required=True, help="股票代码 JSON 数组")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="冒烟测试代码数；0表示全部")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def as_float(value) -> float:
    try:
        return float(value) if value not in (None, "") else math.nan
    except (TypeError, ValueError):
        return math.nan


def save_json(path: pathlib.Path, value: dict | list) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def write_table(rows: list[dict], path: pathlib.Path) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def fetch_trade_calendar(start: str, end: str) -> list[dict]:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login: {login.error_code} {login.error_msg}")
    rows: list[dict] = []
    try:
        result = bs.query_trade_dates(start_date=start, end_date=end)
        while result.error_code == "0" and result.next():
            date, is_trading = result.get_row_data()
            if is_trading == "1":
                rows.append({"date": date})
        if result.error_code != "0":
            raise RuntimeError(
                f"Baostock trade calendar: {result.error_code} {result.error_msg}"
            )
    finally:
        bs.logout()
    return rows


def fetch_tencent_daily(code: str, start: str, end: str) -> list[dict]:
    symbol = code.replace(".", "")
    params = {"param": f"{symbol},day,{start},{end},600,bfq"}
    request = urllib.request.Request(
        TENCENT_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://stock.qq.com/"},
    )
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(
                request, timeout=NETWORK_TIMEOUT_SECONDS
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != 0:
                raise RuntimeError(
                    f"Tencent response: {payload.get('code')} {payload.get('msg')}"
                )
            node = payload.get("data", {}).get(symbol, {})
            source_rows = node.get("day") or []
            if not isinstance(source_rows, list):
                raise RuntimeError("Tencent daily rows are not a list")
            output: list[dict] = []
            previous_close = math.nan
            for raw in source_rows:
                if len(raw) < 6:
                    continue
                date, open_price, close, high, low, volume_lots = raw[:6]
                close_value = as_float(close)
                corporate_action = (
                    raw[6] if len(raw) > 6 and isinstance(raw[6], dict) else None
                )
                pct_chg = (
                    round((close_value / previous_close - 1.0) * 100.0, 8)
                    if math.isfinite(close_value)
                    and math.isfinite(previous_close)
                    and previous_close > 0
                    and corporate_action is None
                    else math.nan
                )
                output.append(
                    {
                        "code": code,
                        "date": date,
                        "open_bfq": as_float(open_price),
                        "high_bfq": as_float(high),
                        "low_bfq": as_float(low),
                        "close_bfq": close_value,
                        "volume_shares": as_float(volume_lots) * 100.0,
                        "pct_chg_bfq": pct_chg,
                        "corporate_action_json": (
                            json.dumps(corporate_action, ensure_ascii=False, sort_keys=True)
                            if corporate_action
                            else None
                        ),
                    }
                )
                previous_close = close_value
            return output
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(0.5 * attempt)
    raise RuntimeError(last_error)


def load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"completed_codes": [], "failures": [], "parts": []}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    if args.workers < 1 or args.workers > 16:
        raise SystemExit("--workers 必须在 1 到 16 之间")
    if args.chunk_size < 1:
        raise SystemExit("--chunk-size 必须大于等于 1")
    start_date = dt.date.fromisoformat(args.start)
    end_date = dt.date.fromisoformat(args.end)
    if start_date > end_date:
        raise SystemExit("--start 不能晚于 --end")

    codes_path = pathlib.Path(args.codes).expanduser().resolve()
    source_codes = json.loads(codes_path.read_text(encoding="utf-8"))
    if not isinstance(source_codes, list) or not all(
        isinstance(code, str) for code in source_codes
    ):
        raise SystemExit("--codes 必须是字符串数组")

    output = pathlib.Path(args.output).expanduser().resolve()
    state_path = output / "state.json"
    if output.exists() and not args.resume:
        raise SystemExit(f"输出目录已存在；若要继续请使用 --resume：{output}")
    output.mkdir(parents=True, exist_ok=True)
    parts_dir = output / "daily"
    parts_dir.mkdir(exist_ok=True)
    codes_snapshot_path = output / "codes.json"
    if codes_snapshot_path.exists():
        codes = json.loads(codes_snapshot_path.read_text(encoding="utf-8"))
    else:
        codes = source_codes[: args.limit] if args.limit > 0 else source_codes
        save_json(codes_snapshot_path, codes)

    calendar_path = output / "trade_calendar.parquet"
    if not calendar_path.exists():
        calendar = fetch_trade_calendar(args.start, args.end)
        if not calendar:
            raise RuntimeError("交易日历为空")
        write_table(calendar, calendar_path)
    else:
        calendar = pq.read_table(calendar_path).to_pylist()

    state = load_state(state_path)
    completed = set(state.get("completed_codes", []))
    pending = [code for code in codes if code not in completed]
    started = time.time()
    print(
        f"CODES total={len(codes)} completed={len(completed)} pending={len(pending)} "
        f"calendar_days={len(calendar)}",
        flush=True,
    )

    for offset in range(0, len(pending), args.chunk_size):
        chunk = pending[offset : offset + args.chunk_size]
        successful: list[str] = []
        failures: list[dict] = []
        rows: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers
        ) as executor:
            futures = {
                executor.submit(
                    fetch_tencent_daily, code, args.start, args.end
                ): code
                for code in chunk
            }
            for future in concurrent.futures.as_completed(futures):
                code = futures[future]
                try:
                    code_rows = future.result()
                    rows.extend(code_rows)
                    successful.append(code)
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        {"code": code, "error": f"{type(exc).__name__}: {exc}"}
                    )

        if successful:
            part_index = len(state.get("parts", []))
            part_path = parts_dir / f"part-{part_index:05d}.parquet"
            if rows:
                rows.sort(key=lambda item: (item["code"], item["date"]))
                write_table(rows, part_path)
                part_value = str(part_path)
            else:
                part_value = None
            state.setdefault("parts", []).append(
                {
                    "path": part_value,
                    "codes": sorted(successful),
                    "rows": len(rows),
                }
            )
            state.setdefault("completed_codes", []).extend(sorted(successful))
        state.setdefault("failures", []).extend(failures)
        state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        state["parameters"] = {
            "codes": str(codes_snapshot_path),
            "source_codes": str(codes_path),
            "start": args.start,
            "end": args.end,
            "workers": args.workers,
            "chunk_size": args.chunk_size,
            "source": "Tencent bfq daily + Baostock trade calendar",
        }
        state["elapsed_seconds_this_run"] = round(time.time() - started, 3)
        save_json(state_path, state)
        print(
            f"CHUNK completed={len(successful)} failed={len(failures)} "
            f"total_completed={len(set(state['completed_codes']))}",
            flush=True,
        )

    unresolved = sorted(
        {item["code"] for item in state.get("failures", [])}
        - set(state.get("completed_codes", []))
    )
    print(
        "RESULT="
        + json.dumps(
            {
                "total_codes": len(codes),
                "completed_codes": len(set(state.get("completed_codes", []))),
                "unresolved_failures": unresolved,
                "parts": len(state.get("parts", [])),
                "elapsed_seconds_this_run": state.get("elapsed_seconds_this_run"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
