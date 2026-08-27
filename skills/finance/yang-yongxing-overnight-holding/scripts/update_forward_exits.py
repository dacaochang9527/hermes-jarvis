#!/usr/bin/env python3
"""用当前交易日分钟行情补齐上一前瞻交易日信号的退出结果。"""

from __future__ import annotations

import argparse
import json
import pathlib

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from analyze_free_prestudy import exits_for_signal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--current-date", required=True)
    parser.add_argument("--current-bars", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = pathlib.Path(args.root).expanduser().resolve()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Output already exists; refusing to overwrite: {output}")

    prior_runs = []
    for day_dir in sorted(root.iterdir() if root.exists() else []):
        if not day_dir.is_dir() or day_dir.name >= args.current_date:
            continue
        for checks in sorted(day_dir.glob("ablation-*/all_tail_checks.parquet")):
            prior_runs.append((day_dir.name, checks))

    result = {
        "current_date": args.current_date,
        "prior_date": None,
        "signal_count": 0,
        "updated_count": 0,
        "rows": [],
    }
    if not prior_runs:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)
        return

    prior_date = max(date for date, _ in prior_runs)
    checks_path = [path for date, path in prior_runs if date == prior_date][-1]
    checks = pq.read_table(checks_path).to_pandas()
    signals = checks[
        checks["resolution"].eq("1m")
        & checks["model"].isin(["M0", "M4_PRE1430_BREAKOUT"])
        & checks["tail_ok"]
    ].copy()
    result["prior_date"] = prior_date
    result["signal_count"] = int(len(signals))
    if signals.empty:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)
        return

    connection = duckdb.connect()
    rows = []
    for _, signal in signals.iterrows():
        bars = connection.execute(
            "SELECT * FROM read_parquet(?) WHERE code=? ORDER BY timestamp",
            [str(pathlib.Path(args.current_bars).resolve()), signal["code"]],
        ).df()
        if bars.empty:
            continue
        bars["date"] = bars["timestamp"].str[:10]
        outcomes = exits_for_signal(bars, str(signal["date"]), float(signal["entry_price"]), "1m")
        if not outcomes or outcomes.get("next_date") != args.current_date:
            continue
        row = {
            "signal_date": str(signal["date"]),
            "model": signal["model"],
            "code": signal["code"],
            "name": signal.get("name", ""),
            "industry": signal.get("industry", "未知"),
            "entry_time": signal.get("entry_time"),
            "entry_price": signal.get("entry_price"),
            **outcomes,
        }
        rows.append(row)

    result["updated_count"] = len(rows)
    result["rows"] = rows
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows:
        pq.write_table(
            pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False),
            output.with_suffix(".parquet"),
            compression="zstd",
        )
    print("RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

