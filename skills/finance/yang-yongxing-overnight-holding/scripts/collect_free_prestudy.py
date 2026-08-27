#!/usr/bin/env python3
"""采集免费预研所需的新浪分钟/日线及 Baostock 时点元数据。"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import random
import re
import time
import urllib.parse
import urllib.request

import baostock as bs
import pyarrow as pa
import pyarrow.parquet as pq


SINA_SPOT = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
SINA_COUNT = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount"
SINA_KLINE = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService.getKLineData"
MAINBOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--end", default="2026-08-19")
    parser.add_argument("--exit-end", default="2026-08-20")
    parser.add_argument("--one-minute-start", default="2026-08-10")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="仅用于冒烟测试；0 表示全部股票")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def is_mainboard(code: str) -> bool:
    if "." not in code:
        return code.startswith(MAINBOARD_PREFIXES)
    exchange, plain = code.split(".", 1)
    if exchange == "sh":
        return plain.startswith(("600", "601", "603", "605"))
    if exchange == "sz":
        return plain.startswith(("000", "001", "002", "003"))
    return False


def sina_symbol(code: str) -> str:
    plain = code.split(".")[-1]
    return ("sh" if plain.startswith("6") else "sz") + plain


def http_get(url: str, params: dict[str, str], attempts: int = 2) -> str:
    full_url = url + "?" + urllib.parse.urlencode(params)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                full_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
            with urllib.request.urlopen(request, timeout=18) as response:
                return response.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.4 + random.random() * 0.8)
    raise RuntimeError(f"HTTP failed: {type(last_error).__name__}: {last_error}")


def parse_jsonp(text: str):
    left = text.find("(")
    right = text.rfind(")")
    if left < 0 or right <= left:
        return None
    return json.loads(text[left + 1 : right])


def fetch_sina_spots() -> list[dict]:
    total = int(http_get(SINA_COUNT, {"node": "hs_a"}).strip('"'))
    rows: list[dict] = []
    page_size = 80
    for page in range(1, (total + page_size - 1) // page_size + 1):
        text = http_get(
            SINA_SPOT,
            {
                "page": str(page),
                "num": str(page_size),
                "sort": "symbol",
                "asc": "1",
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "page",
            },
        )
        page_rows = json.loads(text)
        if isinstance(page_rows, list):
            rows.extend(page_rows)
    return rows


def baostock_context(start: str, exit_end: str):
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {login.error_msg}")
    try:
        rs = bs.query_trade_dates(start_date=start, end_date=exit_end)
        trade_dates: list[str] = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            if row[1] == "1":
                trade_dates.append(row[0])

        snapshot_dates = [trade_dates[0]]
        for date in trade_dates[1:]:
            if date[:7] != snapshot_dates[-1][:7]:
                snapshot_dates.append(date)
        if trade_dates[-1] not in snapshot_dates:
            snapshot_dates.append(trade_dates[-1])

        universe_rows: list[dict] = []
        industry_rows: list[dict] = []
        codes: set[str] = set()
        for index, date in enumerate(snapshot_dates, 1):
            ars = bs.query_all_stock(day=date)
            while ars.error_code == "0" and ars.next():
                code, trade_status, name = ars.get_row_data()
                if not is_mainboard(code):
                    continue
                plain = code.split(".")[-1]
                codes.add(plain)
                universe_rows.append(
                    {
                        "date": date,
                        "code": plain,
                        "name": name,
                        "trade_status": int(trade_status or 0),
                        "is_st_name": bool("ST" in name.upper() or "退" in name),
                    }
                )

            print(f"UNIVERSE {index}/{len(snapshot_dates)} {date}", flush=True)

        for index, date in enumerate(snapshot_dates, 1):
            irs = bs.query_stock_industry(date=date)
            while irs.error_code == "0" and irs.next():
                update_date, code, name, industry, classification = irs.get_row_data()
                if not is_mainboard(code):
                    continue
                industry_rows.append(
                    {
                        "date": date,
                        "update_date": update_date,
                        "code": code.split(".")[-1],
                        "name": name,
                        "industry": industry,
                        "classification": classification,
                    }
                )
            print(f"INDUSTRY {index}/{len(snapshot_dates)} {date}", flush=True)
        return trade_dates, sorted(codes), universe_rows, industry_rows
    finally:
        bs.logout()


def fetch_kline(code: str, scale: int, datalen: int) -> list[dict]:
    text = http_get(
        SINA_KLINE,
        {
            "symbol": sina_symbol(code),
            "scale": str(scale),
            "ma": "no",
            "datalen": str(datalen),
        },
    )
    rows = parse_jsonp(text)
    if not isinstance(rows, list):
        raise RuntimeError("invalid JSONP payload")
    return rows


def numeric(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_intraday(code: str, rows: list[dict], start: str, end: str) -> list[dict]:
    output = []
    for raw in rows:
        timestamp = str(raw.get("day", ""))[:19]
        date = timestamp[:10]
        if not (start <= date <= end):
            continue
        output.append(
            {
                "code": code,
                "timestamp": timestamp,
                "open": numeric(raw.get("open")),
                "high": numeric(raw.get("high")),
                "low": numeric(raw.get("low")),
                "close": numeric(raw.get("close")),
                "volume": numeric(raw.get("volume")),
                "amount": numeric(raw.get("amount")),
            }
        )
    return output


def normalize_daily(code: str, rows: list[dict]) -> list[dict]:
    output = []
    for raw in rows:
        date = str(raw.get("day", ""))[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        output.append(
            {
                "code": code,
                "date": date,
                "open": numeric(raw.get("open")),
                "high": numeric(raw.get("high")),
                "low": numeric(raw.get("low")),
                "close": numeric(raw.get("close")),
                "volume": numeric(raw.get("volume")),
                "amount": numeric(raw.get("amount")),
            }
        )
    return output


def fetch_symbol_bundle(code: str, start: str, exit_end: str, one_minute_start: str):
    result = {"code": code, "bars_5m": [], "bars_1m": [], "daily": [], "errors": []}
    for scale, key, datalen, filter_start in (
        (5, "bars_5m", 1970, start),
        (1, "bars_1m", 1970, one_minute_start),
        (240, "daily", 220, ""),
    ):
        try:
            raw = fetch_kline(code, scale, datalen)
            if scale == 240:
                result[key] = normalize_daily(code, raw)
            else:
                result[key] = normalize_intraday(code, raw, filter_start, exit_end)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"scale={scale}: {type(exc).__name__}: {exc}")
    return result


BAR_SCHEMA = pa.schema(
    [
        ("code", pa.string()),
        ("timestamp", pa.string()),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
        ("amount", pa.float64()),
    ]
)
DAILY_SCHEMA = pa.schema(
    [
        ("code", pa.string()),
        ("date", pa.string()),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
        ("amount", pa.float64()),
    ]
)


def write_rows(writer: pq.ParquetWriter, rows: list[dict], schema: pa.Schema):
    if rows:
        writer.write_table(pa.Table.from_pylist(rows, schema=schema))


def main() -> None:
    args = parse_args()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Output already exists; refusing to overwrite: {output}")
    output.mkdir(parents=True)

    print("Collecting Baostock point-in-time context", flush=True)
    trade_dates, codes, universe_rows, industry_rows = baostock_context(args.start, args.exit_end)
    if args.limit > 0:
        codes = codes[: args.limit]
        selected = set(codes)
        universe_rows = [row for row in universe_rows if row["code"] in selected]
        industry_rows = [row for row in industry_rows if row["code"] in selected]
    pq.write_table(pa.Table.from_pylist(universe_rows), output / "universe.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(industry_rows), output / "industry.parquet", compression="zstd")

    print("Collecting current Sina spot metadata", flush=True)
    spots = fetch_sina_spots()
    spot_rows = [row for row in spots if is_mainboard(str(row.get("code", "")))]
    (output / "spot_metadata.json").write_text(
        json.dumps(spot_rows, ensure_ascii=False), encoding="utf-8"
    )

    five_path = output / "bars_5m.parquet"
    one_path = output / "bars_1m.parquet"
    daily_path = output / "daily.parquet"
    five_writer = pq.ParquetWriter(five_path, BAR_SCHEMA, compression="zstd")
    one_writer = pq.ParquetWriter(one_path, BAR_SCHEMA, compression="zstd")
    daily_writer = pq.ParquetWriter(daily_path, DAILY_SCHEMA, compression="zstd")
    failures: list[dict] = []
    counts = {"symbols": len(codes), "bars_5m": 0, "bars_1m": 0, "daily": 0}
    started = time.time()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    fetch_symbol_bundle, code, args.start, args.exit_end, args.one_minute_start
                ): code
                for code in codes
            }
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                code = futures[future]
                try:
                    bundle = future.result()
                    write_rows(five_writer, bundle["bars_5m"], BAR_SCHEMA)
                    write_rows(one_writer, bundle["bars_1m"], BAR_SCHEMA)
                    write_rows(daily_writer, bundle["daily"], DAILY_SCHEMA)
                    counts["bars_5m"] += len(bundle["bars_5m"])
                    counts["bars_1m"] += len(bundle["bars_1m"])
                    counts["daily"] += len(bundle["daily"])
                    if bundle["errors"]:
                        failures.append({"code": code, "errors": bundle["errors"]})
                except Exception as exc:  # noqa: BLE001
                    failures.append({"code": code, "errors": [f"bundle: {type(exc).__name__}: {exc}"]})
                if index % 100 == 0 or index == len(codes):
                    print(
                        f"SYMBOLS {index}/{len(codes)} rows5={counts['bars_5m']} "
                        f"rows1={counts['bars_1m']} failures={len(failures)}",
                        flush=True,
                    )
    finally:
        five_writer.close()
        one_writer.close()
        daily_writer.close()

    report = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "parameters": vars(args),
        "trade_dates": trade_dates,
        "counts": counts,
        "universe_rows": len(universe_rows),
        "industry_rows": len(industry_rows),
        "failure_count": len(failures),
        "failures": failures,
        "elapsed_seconds": round(time.time() - started, 2),
        "files": {
            path.name: {"bytes": path.stat().st_size, "rows": pq.ParquetFile(path).metadata.num_rows}
            for path in (five_path, one_path, daily_path, output / "universe.parquet", output / "industry.parquet")
        },
    }
    (output / "coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("RESULT=" + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
