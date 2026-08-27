#!/usr/bin/env python3
"""Collect a bounded forward 5-minute window from Eastmoney for R2 screening."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import random
import time
import urllib.parse
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq


ENDPOINT = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
FIELDS1 = "f1,f2,f3,f4,f5,f6"
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
EXPECTED_TIMES = tuple(
    [f"09:{minute:02d}" for minute in range(35, 60, 5)]
    + [f"10:{minute:02d}" for minute in range(0, 60, 5)]
    + [f"11:{minute:02d}" for minute in range(0, 31, 5)]
    + [f"13:{minute:02d}" for minute in range(5, 60, 5)]
    + [f"14:{minute:02d}" for minute in range(0, 60, 5)]
    + ["15:00"]
)
BAR_SCHEMA = pa.schema(
    [
        ("code", pa.string()),
        ("timestamp", pa.string()),
        ("open", pa.float64()),
        ("close", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("volume", pa.float64()),
        ("amount", pa.float64()),
        ("source", pa.string()),
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def secid(code: str) -> str:
    return ("1." if code.startswith("6") else "0.") + code


def fetch(code: str, start: str, end: str, attempts: int = 4) -> dict:
    params = {
        "secid": secid(code),
        "klt": "5",
        "fqt": "0",
        "beg": start.replace("-", ""),
        "end": end.replace("-", ""),
        "fields1": FIELDS1,
        "fields2": FIELDS2,
    }
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://quote.eastmoney.com/",
                },
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.load(response)
            data = payload.get("data")
            if payload.get("rc") != 0 or not isinstance(data, dict):
                raise RuntimeError(f"invalid payload rc={payload.get('rc')}")
            rows: list[dict] = []
            for raw in data.get("klines") or []:
                values = raw.split(",")
                if len(values) < 8:
                    continue
                timestamp = values[0]
                if not (start <= timestamp[:10] <= end):
                    continue
                rows.append(
                    {
                        "code": code,
                        "timestamp": timestamp,
                        "open": float(values[1]),
                        "close": float(values[2]),
                        "high": float(values[3]),
                        "low": float(values[4]),
                        # Eastmoney's f56 is in board lots; R2/Baostock uses shares.
                        "volume": float(values[5]) * 100.0,
                        "amount": float(values[6]),
                        "source": "eastmoney_push2his",
                    }
                )
            return {"code": code, "rows": rows, "error": None}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt) + random.random() * 0.5)
    return {"code": code, "rows": [], "error": " | ".join(errors)}


def main() -> None:
    args = parse_args()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Output already exists; refusing to overwrite: {output}")
    output.mkdir(parents=True)

    universe = pq.read_table(args.universe).to_pylist()
    codes = sorted(
        {
            str(row["code"]).split(".")[-1]
            for row in universe
            if str(row.get("date") or row.get("snapshot_date")) == args.end
        }
    )
    if args.limit > 0:
        codes = codes[: args.limit]

    writer = pq.ParquetWriter(output / "bars_5m.parquet", BAR_SCHEMA, compression="zstd")
    failures: list[dict] = []
    empty: list[str] = []
    rows_written = 0
    started = time.time()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(fetch, code, args.start, args.end): code for code in codes}
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                result = future.result()
                if result["error"]:
                    failures.append({"code": result["code"], "error": result["error"]})
                elif not result["rows"]:
                    empty.append(result["code"])
                else:
                    writer.write_table(pa.Table.from_pylist(result["rows"], schema=BAR_SCHEMA))
                    rows_written += len(result["rows"])
                if index % 200 == 0 or index == len(codes):
                    print(
                        f"SYMBOLS {index}/{len(codes)} rows={rows_written} "
                        f"failures={len(failures)} empty={len(empty)}",
                        flush=True,
                    )
    finally:
        writer.close()

    bars = pq.read_table(output / "bars_5m.parquet", columns=["code", "timestamp"]).to_pylist()
    by_key: dict[tuple[str, str], list[str]] = {}
    for row in bars:
        key = (row["code"], row["timestamp"][:10])
        by_key.setdefault(key, []).append(row["timestamp"][11:16])
    dates = []
    current = dt.date.fromisoformat(args.start)
    final = dt.date.fromisoformat(args.end)
    while current <= final:
        dates.append(current.isoformat())
        current += dt.timedelta(days=1)
    completeness = {
        date: {
            "symbols_with_rows": sum(bool(by_key.get((code, date))) for code in codes),
            "symbols_exact_48": sum(
                len(by_key.get((code, date), [])) == 48
                and set(by_key.get((code, date), [])) == set(EXPECTED_TIMES)
                for code in codes
            ),
        }
        for date in dates
    }
    report = {
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "parameters": vars(args),
        "symbols": len(codes),
        "rows": rows_written,
        "failure_count": len(failures),
        "failures": failures,
        "empty_count": len(empty),
        "empty_codes": empty,
        "completeness": completeness,
        "elapsed_seconds": round(time.time() - started, 2),
        "source": "eastmoney_push2his",
    }
    (output / "coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("RESULT=" + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
