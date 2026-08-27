#!/usr/bin/env python3
"""Collect an R2 forward day after an exact, historical-volume prefilter."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib

import baostock as bs
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from collect_stage_c_5m import (
    BaostockSessionError,
    EXPECTED_5M_TIMES,
    daily_is_valid,
    initial_login,
    query_5m,
    query_daily,
    save_json,
    trade_dates,
)


BAR_SCHEMA = pa.schema(
    [
        ("date", pa.string()),
        ("time", pa.string()),
        ("code", pa.string()),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
        ("amount", pa.float64()),
        ("source", pa.string()),
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--daily-glob", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def load_prefilter_codes(daily_glob: str, prior_date: str) -> list[str]:
    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        SELECT code FROM read_parquet(?)
        WHERE date=? AND trade_status=1 AND NOT is_st
          AND listing_market_days_prior>=60
          AND volume_ma120_d2_complete AND volume_ma120_d2_ok
        ORDER BY code
        """,
        [daily_glob, prior_date],
    ).fetchall()
    return [row[0] for row in rows]


def volume_check(rows: list[dict], calendar: list[str], signal_date: str) -> dict:
    by_date = {row["date"]: row for row in rows}
    position = calendar.index(signal_date)
    prior_dates = calendar[position - 3 : position]
    details: list[dict] = []
    for date in prior_dates:
        index = calendar.index(date)
        window_dates = calendar[index - 119 : index + 1] if index >= 119 else []
        window_rows = [by_date.get(item) for item in window_dates]
        complete = len(window_rows) == 120 and all(daily_is_valid(item) for item in window_rows)
        average = (
            sum(item["volume"] for item in window_rows if item is not None) / 120.0
            if complete
            else math.nan
        )
        current = by_date.get(date)
        volume = current["volume"] if current is not None else math.nan
        passed = complete and math.isfinite(volume) and volume > average
        details.append(
            {
                "date": date,
                "complete": complete,
                "volume": volume,
                "ma120_including_current": average,
                "passed": passed,
            }
        )
    return {
        "prior_dates": prior_dates,
        "details": details,
        "passed": len(details) == 3 and all(item["passed"] for item in details),
    }


def bar_rows(raw_rows: list[list[str]]) -> list[dict]:
    output: list[dict] = []
    for row in raw_rows:
        output.append(
            {
                "date": row[0],
                "time": row[1][8:12],
                "code": row[2],
                "open": float(row[3]),
                "high": float(row[4]),
                "low": float(row[5]),
                "close": float(row[6]),
                "volume": float(row[7]),
                "amount": float(row[8]),
                "source": "baostock",
            }
        )
    return output


def exact_day(rows: list[dict], date: str) -> bool:
    times = [row["time"] for row in rows if row["date"] == date]
    return len(times) == len(EXPECTED_5M_TIMES) and set(times) == set(EXPECTED_5M_TIMES)


def main() -> None:
    args = parse_args()
    output = pathlib.Path(args.output).expanduser().resolve()
    state_path = output / "state.json"
    bars_dir = output / "bars"
    if output.exists() and not args.resume:
        raise SystemExit(f"Output already exists; pass --resume: {output}")
    output.mkdir(parents=True, exist_ok=True)
    bars_dir.mkdir(exist_ok=True)

    signal = dt.date.fromisoformat(args.date)
    lookback = (signal - dt.timedelta(days=520)).isoformat()
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if args.resume and state_path.is_file()
        else {
            "status": "RUNNING",
            "parameters": vars(args),
            "completed_codes": [],
            "volume_pass_codes": [],
            "checks": [],
            "failures": [],
        }
    )

    initial_login()
    try:
        calendar = trade_dates(lookback, args.date)
        position = calendar.index(args.date)
        prior_date = calendar[position - 1]
        codes = load_prefilter_codes(args.daily_glob, prior_date)
        state["total_prefilter_codes"] = len(codes)
        state["signal_date"] = args.date
        state["prior_date"] = prior_date
        completed = set(state["completed_codes"])

        for index, code in enumerate(codes, 1):
            if code in completed:
                continue
            try:
                daily = query_daily(code, lookback, prior_date)
                check = {"code": code, **volume_check(daily, calendar, args.date)}
                state["checks"].append(check)
                if check["passed"]:
                    raw = query_5m(code, prior_date, args.date)
                    rows = bar_rows(raw)
                    check["prior_exact_48"] = exact_day(rows, prior_date)
                    check["signal_exact_48"] = exact_day(rows, args.date)
                    if check["prior_exact_48"] and check["signal_exact_48"]:
                        part = bars_dir / (code.replace(".", "_") + ".parquet")
                        pq.write_table(pa.Table.from_pylist(rows, schema=BAR_SCHEMA), part, compression="zstd")
                        state["volume_pass_codes"].append(code)
                    else:
                        state["failures"].append(
                            {"code": code, "error": "INCOMPLETE_5M", "check": check}
                        )
                state["completed_codes"].append(code)
                completed.add(code)
            except BaostockSessionError as exc:
                state["status"] = "BLACKLIST_STOPPED"
                state["failures"].append({"code": code, "error": str(exc)})
                save_json(state_path, state)
                raise
            except Exception as exc:  # noqa: BLE001
                state["failures"].append(
                    {"code": code, "error": f"{type(exc).__name__}: {exc}"}
                )
                state["completed_codes"].append(code)
                completed.add(code)
            if index % 20 == 0 or index == len(codes):
                save_json(state_path, state)
                print(
                    f"CODES {len(completed)}/{len(codes)} "
                    f"volume_pass={len(state['volume_pass_codes'])} "
                    f"failures={len(state['failures'])}",
                    flush=True,
                )

        state["status"] = "COMPLETE" if not state["failures"] else "COMPLETE_WITH_FAILURES"
        save_json(state_path, state)
        print(
            "RESULT="
            + json.dumps(
                {
                    "status": state["status"],
                    "total_prefilter_codes": len(codes),
                    "completed_codes": len(completed),
                    "volume_pass_codes": len(state["volume_pass_codes"]),
                    "failures": len(state["failures"]),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        bs.logout()


if __name__ == "__main__":
    main()
