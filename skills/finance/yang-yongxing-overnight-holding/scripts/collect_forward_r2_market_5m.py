#!/usr/bin/env python3
"""Collect the full eligible-market 5-minute cross-section for an R2 forward day."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shutil

import baostock as bs
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from collect_stage_c_5m import (
    BaostockSessionError,
    EXPECTED_5M_TIMES,
    initial_login,
    query_5m,
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
    parser.add_argument("--seed-bars")
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def static_codes(daily_glob: str, prior_date: str) -> list[str]:
    connection = duckdb.connect()
    rows = connection.execute(
        """
        SELECT code FROM read_parquet(?)
        WHERE date=? AND trade_status=1 AND NOT is_st
          AND listing_market_days_prior>=60
        ORDER BY code
        """,
        [daily_glob, prior_date],
    ).fetchall()
    return [row[0] for row in rows]


def bar_rows(raw_rows: list[list[str]]) -> list[dict]:
    return [
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
        for row in raw_rows
    ]


def exact_day(rows: list[dict], date: str) -> bool:
    times = [row["time"] for row in rows if row["date"] == date]
    return len(times) == len(EXPECTED_5M_TIMES) and set(times) == set(EXPECTED_5M_TIMES)


def main() -> None:
    args = parse_args()
    output = pathlib.Path(args.output).expanduser().resolve()
    bars_dir = output / "bars"
    state_path = output / "state.json"
    if output.exists() and not args.resume:
        raise SystemExit(f"Output already exists; pass --resume: {output}")
    output.mkdir(parents=True, exist_ok=True)
    bars_dir.mkdir(exist_ok=True)

    signal = dt.date.fromisoformat(args.date)
    calendar_start = (signal - dt.timedelta(days=14)).isoformat()
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if args.resume and state_path.is_file()
        else {
            "status": "RUNNING",
            "parameters": vars(args),
            "completed_codes": [],
            "failures": [],
            "seeded_codes": [],
        }
    )

    if args.seed_bars and not state["seeded_codes"]:
        seed = pathlib.Path(args.seed_bars).expanduser().resolve()
        for source in sorted(seed.glob("*.parquet")):
            destination = bars_dir / source.name
            if not destination.exists():
                shutil.copy2(source, destination)
            state["seeded_codes"].append(source.stem.replace("_", ".", 1))
        save_json(state_path, state)

    initial_login()
    try:
        calendar = trade_dates(calendar_start, args.date)
        position = calendar.index(args.date)
        prior_date = calendar[position - 1]
        codes = static_codes(args.daily_glob, prior_date)
        state["total_codes"] = len(codes)
        state["prior_date"] = prior_date
        completed = set(state["completed_codes"]) | set(state["seeded_codes"])

        for index, code in enumerate(codes, 1):
            if code in completed:
                continue
            try:
                rows = bar_rows(query_5m(code, prior_date, args.date))
                if exact_day(rows, prior_date) and exact_day(rows, args.date):
                    part = bars_dir / (code.replace(".", "_") + ".parquet")
                    pq.write_table(pa.Table.from_pylist(rows, schema=BAR_SCHEMA), part, compression="zstd")
                else:
                    state["failures"].append({"code": code, "error": "INCOMPLETE_5M"})
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
            if index % 50 == 0 or index == len(codes):
                save_json(state_path, state)
                print(
                    f"CODES {len(completed)}/{len(codes)} "
                    f"seeded={len(state['seeded_codes'])} failures={len(state['failures'])}",
                    flush=True,
                )

        expected_files = {code.replace(".", "_") + ".parquet" for code in codes}
        actual_files = {path.name for path in bars_dir.glob("*.parquet")}
        missing = sorted(expected_files - actual_files)
        state["missing_files"] = missing
        state["status"] = (
            "COMPLETE" if not state["failures"] and not missing else "COMPLETE_WITH_FAILURES"
        )
        save_json(state_path, state)
        print(
            "RESULT="
            + json.dumps(
                {
                    "status": state["status"],
                    "total_codes": len(codes),
                    "bars_files": len(actual_files),
                    "failures": len(state["failures"]),
                    "missing": len(missing),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        bs.logout()


if __name__ == "__main__":
    main()
