#!/usr/bin/env python3
"""采集多年 Baostock 5 分钟数据并按股票日立即聚合。

本脚本只为“经济路线”基础条件验证生成数据，不验证分钟级尾盘结构。
输出采用分片 Parquet 和状态文件，支持在中断后通过 --resume 继续。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import socket
import time
from collections import defaultdict

import baostock as bs
import pyarrow as pa
import pyarrow.parquet as pq


MAINBOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
NETWORK_TIMEOUT_SECONDS = 45
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
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=0, help="冒烟测试股票数；0 表示全部")
    parser.add_argument("--chunk-size", type=int, default=25)
    parser.add_argument(
        "--workers",
        type=int,
        choices=(1,),
        default=1,
        help="Baostock 免费接口按单会话串行采集，只允许 1",
    )
    parser.add_argument("--resume", action="store_true")
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


def as_float(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else math.nan
    except (TypeError, ValueError):
        return math.nan


def trade_dates(start: str, end: str) -> list[str]:
    rs = bs.query_trade_dates(start_date=start, end_date=end)
    rows: list[str] = []
    while rs.error_code == "0" and rs.next():
        date, is_trading = rs.get_row_data()
        if is_trading == "1":
            rows.append(date)
    if rs.error_code != "0":
        raise RuntimeError(f"query_trade_dates failed: {rs.error_code} {rs.error_msg}")
    return rows


def next_trade_date(end: str) -> str:
    end_date = dt.date.fromisoformat(end)
    dates = trade_dates(end, (end_date + dt.timedelta(days=14)).isoformat())
    later = [date for date in dates if date > end]
    if not later:
        raise RuntimeError(f"无法找到 {end} 之后的交易日")
    return later[0]


def snapshot_dates(dates: list[str]) -> list[str]:
    selected: list[str] = []
    previous_month = ""
    for date in dates:
        month = date[:7]
        if month != previous_month:
            selected.append(date)
            previous_month = month
    if dates and dates[-1] not in selected:
        selected.append(dates[-1])
    return selected


def collect_context(dates: list[str]) -> tuple[list[str], list[dict], list[dict]]:
    codes: set[str] = set()
    universe: list[dict] = []
    industry: list[dict] = []
    for date in snapshot_dates(dates):
        rs = bs.query_all_stock(day=date)
        while rs.error_code == "0" and rs.next():
            code, trade_status, name = rs.get_row_data()
            if not is_mainboard(code):
                continue
            codes.add(code)
            universe.append(
                {
                    "snapshot_date": date,
                    "code": code,
                    "name": name,
                    "trade_status": int(trade_status or 0),
                    "is_st_name": "ST" in name.upper() or "退" in name,
                }
            )
        if rs.error_code != "0":
            raise RuntimeError(f"query_all_stock {date}: {rs.error_code} {rs.error_msg}")

        irs = bs.query_stock_industry(date=date)
        while irs.error_code == "0" and irs.next():
            update_date, code, name, industry_name, classification = irs.get_row_data()
            if not is_mainboard(code):
                continue
            industry.append(
                {
                    "snapshot_date": date,
                    "update_date": update_date,
                    "code": code,
                    "name": name,
                    "industry": industry_name,
                    "classification": classification,
                }
            )
        if irs.error_code != "0":
            raise RuntimeError(
                f"query_stock_industry {date}: {irs.error_code} {irs.error_msg}"
            )
    return sorted(codes), universe, industry


def query_daily(code: str, start: str, end: str) -> list[dict]:
    fields = (
        "date,code,open,high,low,close,preclose,volume,amount,turn,"
        "tradestatus,pctChg,isST"
    )
    rs = bs.query_history_k_data_plus(
        code,
        fields,
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag="3",
    )
    rows: list[dict] = []
    names = fields.split(",")
    while rs.error_code == "0" and rs.next():
        raw = dict(zip(names, rs.get_row_data()))
        rows.append(
            {
                "date": raw["date"],
                "close": as_float(raw["close"]),
                "preclose": as_float(raw["preclose"]),
                "volume": as_float(raw["volume"]),
                "amount": as_float(raw["amount"]),
                "turn": as_float(raw["turn"]),
                "pct": as_float(raw["pctChg"]),
                "trade_status": int(raw["tradestatus"] or 0),
                "is_st": raw["isST"] == "1",
            }
        )
    if rs.error_code != "0":
        raise RuntimeError(f"daily {code}: {rs.error_code} {rs.error_msg}")
    return rows


def month_ranges(start: str, end: str) -> list[tuple[str, str]]:
    current = dt.date.fromisoformat(start).replace(day=1)
    end_date = dt.date.fromisoformat(end)
    ranges: list[tuple[str, str]] = []
    while current <= end_date:
        if current.month == 12:
            next_month = dt.date(current.year + 1, 1, 1)
        else:
            next_month = dt.date(current.year, current.month + 1, 1)
        segment_start = max(current, dt.date.fromisoformat(start))
        segment_end = min(next_month - dt.timedelta(days=1), end_date)
        ranges.append((segment_start.isoformat(), segment_end.isoformat()))
        current = next_month
    return ranges


def query_5m(code: str, start: str, end: str) -> list[list[str]]:
    fields = "date,time,code,open,high,low,close,volume,amount,adjustflag"
    rows: list[list[str]] = []
    for segment_start, segment_end in month_ranges(start, end):
        last_error = ""
        for attempt in range(2):
            rs = bs.query_history_k_data_plus(
                code,
                fields,
                start_date=segment_start,
                end_date=segment_end,
                frequency="5",
                adjustflag="3",
            )
            segment_rows: list[list[str]] = []
            while rs.error_code == "0" and rs.next():
                segment_rows.append(rs.get_row_data())
            if rs.error_code == "0":
                rows.extend(segment_rows)
                break
            last_error = f"{rs.error_code} {rs.error_msg}"
            if rs.error_code == "10001001" and attempt == 0:
                login = bs.login()
                if login.error_code == "0":
                    continue
                last_error += f"; relogin={login.error_code} {login.error_msg}"
            raise RuntimeError(
                f"5m {code} {segment_start}..{segment_end}: {last_error}"
            )
    return rows


def daily_feature_map(rows: list[dict]) -> dict[str, dict]:
    output: dict[str, dict] = {}
    ma120_ok: list[bool | None] = []
    for index, row in enumerate(rows):
        if index >= 119:
            window = [item["volume"] for item in rows[index - 119 : index + 1]]
            valid = all(math.isfinite(value) for value in window)
            mean_volume = sum(window) / 120 if valid else math.nan
            ma120_ok.append(valid and row["volume"] > mean_volume)
        else:
            ma120_ok.append(None)

        previous5 = rows[max(0, index - 5) : index]
        previous20 = rows[max(0, index - 20) : index]
        previous3_indexes = range(max(0, index - 3), index)
        prev5_valid = len(previous5) == 5 and all(
            math.isfinite(item["volume"]) for item in previous5
        )
        prev5_volume = (
            sum(item["volume"] for item in previous5) / 5 if prev5_valid else math.nan
        )
        recent_strong = len(previous20) == 20 and any(
            math.isfinite(item["pct"]) and item["pct"] >= 5.0 for item in previous20
        )
        volume3_ok = index >= 3 and all(ma120_ok[item] is True for item in previous3_indexes)
        float_shares = (
            row["volume"] / (row["turn"] / 100.0)
            if math.isfinite(row["volume"])
            and math.isfinite(row["turn"])
            and row["turn"] > 0
            else math.nan
        )
        output[row["date"]] = {
            "preclose": row["preclose"],
            "prev5_volume": prev5_volume,
            "recent20_complete": len(previous20) == 20,
            "recent_strong": recent_strong,
            "volume3_complete": index >= 122,
            "volume3_ok": volume3_ok,
            "listing_days_prior": index,
            "trade_status": row["trade_status"],
            "is_st": row["is_st"],
            "float_shares_inferred": float_shares,
            "daily_turnover": row["turn"],
        }
    return output


def intraday_aggregates(rows: list[list[str]]) -> dict[str, dict]:
    grouped: dict[str, list[list[str]]] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(row)

    output: dict[str, dict] = {}
    for date, bars in grouped.items():
        source_times = [row[1][8:12] for row in bars]
        source_out_of_order_count = sum(
            current < previous
            for previous, current in zip(source_times, source_times[1:])
        )
        source_times1430 = [time for time in source_times if time <= "1430"]
        source_out_of_order_count1430 = sum(
            current < previous
            for previous, current in zip(source_times1430, source_times1430[1:])
        )
        bars.sort(key=lambda item: item[1])
        times = [row[1][8:12] for row in bars]
        times1430 = [time for time in times if time <= "1430"]
        time_set = set(times)
        time1430_set = set(times1430)
        expected_set = set(EXPECTED_5M_TIMES)
        expected1430_set = set(EXPECTED_5M_TIMES_1430)
        duplicate_bar_count = len(times) - len(time_set)
        duplicate_bar_count1430 = len(times1430) - len(time1430_set)
        unexpected_bar_count = len(time_set - expected_set)
        unexpected_bar_count1430 = len(time1430_set - expected1430_set)
        missing_expected_bar_count = len(expected_set - time_set)
        missing_expected_bar_count1430 = len(expected1430_set - time1430_set)
        has_1430_bar = times.count("1430") == 1
        exact_1430_complete = (
            len(times1430) == len(EXPECTED_5M_TIMES_1430)
            and len(time1430_set) == len(EXPECTED_5M_TIMES_1430)
            and duplicate_bar_count1430 == 0
            and unexpected_bar_count1430 == 0
            and missing_expected_bar_count1430 == 0
            and has_1430_bar
            and source_out_of_order_count1430 == 0
        )
        cumulative_volume = 0.0
        cumulative_amount = 0.0
        price1430 = math.nan
        volume1430 = math.nan
        amount1430 = math.nan
        strength_count = 0
        above_vwap_count = 0
        morning_volume = 0.0
        morning_amount = 0.0
        first_vwap = math.nan
        for row in bars:
            timestamp = row[1]
            tm = timestamp[8:12]
            close = as_float(row[6])
            volume = as_float(row[7])
            amount = as_float(row[8])
            if not math.isfinite(volume):
                volume = 0.0
            if not math.isfinite(amount):
                amount = 0.0
            cumulative_volume += volume
            cumulative_amount += amount
            if tm <= "1430":
                price1430 = close
                volume1430 = cumulative_volume
                amount1430 = cumulative_amount
            if "1000" <= tm <= "1430":
                strength_count += 1
                vwap = cumulative_amount / cumulative_volume if cumulative_volume > 0 else math.nan
                if math.isfinite(close) and math.isfinite(vwap) and close >= vwap:
                    above_vwap_count += 1
            if tm == "0935" and volume > 0:
                first_vwap = amount / volume
            if "0935" <= tm <= "1000":
                morning_volume += volume
                morning_amount += amount
        output[date] = {
            "bar_count": len(bars),
            "distinct_bar_count": len(time_set),
            "duplicate_bar_count": duplicate_bar_count,
            "unexpected_bar_count": unexpected_bar_count,
            "missing_expected_bar_count": missing_expected_bar_count,
            "source_out_of_order_count": source_out_of_order_count,
            "source_out_of_order_count1430": source_out_of_order_count1430,
            "first_bar_time": bars[0][1][8:12] if bars else "",
            "last_bar_time": bars[-1][1][8:12] if bars else "",
            "bar_count1430": len(times1430),
            "distinct_bar_count1430": len(time1430_set),
            "duplicate_bar_count1430": duplicate_bar_count1430,
            "unexpected_bar_count1430": unexpected_bar_count1430,
            "missing_expected_bar_count1430": missing_expected_bar_count1430,
            "has_1430_bar": has_1430_bar,
            "exact_1430_complete": exact_1430_complete,
            "price1430": price1430,
            "cum_volume1430": volume1430,
            "cum_amount1430": amount1430,
            "vwap1430": amount1430 / volume1430 if volume1430 > 0 else math.nan,
            "strength_5m_count": strength_count,
            "above_vwap_5m_count": above_vwap_count,
            "above_vwap_5m_ratio": (
                above_vwap_count / strength_count if strength_count > 0 else math.nan
            ),
            "exit_first_5m_vwap": first_vwap,
            "exit_to_1000_vwap": (
                morning_amount / morning_volume if morning_volume > 0 else math.nan
            ),
        }
    return output


def collect_code(code: str, start: str, end: str, exit_end: str) -> list[dict]:
    lookback = (dt.date.fromisoformat(start) - dt.timedelta(days=260)).isoformat()
    daily = daily_feature_map(query_daily(code, lookback, exit_end))
    intraday = intraday_aggregates(query_5m(code, start, exit_end))
    rows: list[dict] = []
    for date in sorted(item for item in intraday if start <= item <= end):
        bar = intraday[date]
        day = daily.get(date, {})
        preclose = day.get("preclose", math.nan)
        price1430 = bar["price1430"]
        volume1430 = bar["cum_volume1430"]
        prev5_volume = day.get("prev5_volume", math.nan)
        float_shares = day.get("float_shares_inferred", math.nan)
        ret1430 = (
            (price1430 / preclose - 1.0) * 100.0
            if math.isfinite(price1430) and math.isfinite(preclose) and preclose > 0
            else math.nan
        )
        volume_ratio = (
            (volume1430 / 210.0) / (prev5_volume / 240.0)
            if math.isfinite(volume1430)
            and math.isfinite(prev5_volume)
            and prev5_volume > 0
            else math.nan
        )
        turnover1430 = (
            volume1430 / float_shares * 100.0
            if math.isfinite(volume1430)
            and math.isfinite(float_shares)
            and float_shares > 0
            else math.nan
        )
        next_dates = [item for item in intraday if item > date]
        next_date = min(next_dates) if next_dates else ""
        next_bar = intraday.get(next_date, {})
        rows.append(
            {
                "code": code,
                "date": date,
                **bar,
                **day,
                "ret1430": ret1430,
                "volume_ratio1430": volume_ratio,
                "turnover1430_inferred": turnover1430,
                "next_date": next_date,
                "next_exit_first_5m_vwap": next_bar.get("exit_first_5m_vwap", math.nan),
                "next_exit_to_1000_vwap": next_bar.get("exit_to_1000_vwap", math.nan),
            }
        )
    return rows


def write_table(rows: list[dict], path: pathlib.Path) -> None:
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")


def load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"completed_codes": [], "failures": [], "parts": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: pathlib.Path, value: dict | list) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def persist_result(
    result: dict,
    state: dict,
    state_path: pathlib.Path,
    parts_dir: pathlib.Path,
    args: argparse.Namespace,
    exit_end: str,
    started: float,
) -> None:
    successful = result["successful"]
    failures = result["failures"]
    if successful:
        part_index = len(state["parts"])
        part_path = parts_dir / f"part-{part_index:05d}.parquet"
        write_table(result["rows"], part_path)
        state["parts"].append(
            {"path": str(part_path), "codes": successful, "rows": len(result["rows"])}
        )
        state["completed_codes"].extend(successful)
    state["failures"].extend(failures)
    state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    state["parameters"] = vars(args)
    state["exit_end"] = exit_end
    state["elapsed_seconds_this_run"] = round(time.time() - started, 3)
    save_json(state_path, state)
    print(
        f"CHUNK completed={len(successful)} failed={len(failures)} "
        f"total_completed={len(state['completed_codes'])}",
        flush=True,
    )


def main() -> None:
    args = parse_args()
    if args.chunk_size < 1:
        raise SystemExit("--chunk-size 必须大于等于 1")
    output = pathlib.Path(args.output).expanduser().resolve()
    state_path = output / "state.json"
    if output.exists() and not args.resume:
        raise SystemExit(f"输出目录已存在；若要继续请使用 --resume：{output}")
    output.mkdir(parents=True, exist_ok=True)
    parts_dir = output / "features"
    parts_dir.mkdir(exist_ok=True)

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {login.error_code} {login.error_msg}")
    started = time.time()
    try:
        exit_end = next_trade_date(args.end)
        dates = trade_dates(args.start, exit_end)
        state = load_state(state_path)
        if not (output / "universe.parquet").exists():
            codes, universe, industry = collect_context(dates)
            if args.limit > 0:
                codes = codes[: args.limit]
                selected = set(codes)
                universe = [row for row in universe if row["code"] in selected]
                industry = [row for row in industry if row["code"] in selected]
            write_table(universe, output / "universe.parquet")
            write_table(industry, output / "industry.parquet")
            save_json(output / "codes.json", codes)
        else:
            codes = json.loads((output / "codes.json").read_text(encoding="utf-8"))

        completed = set(state["completed_codes"])
        pending = [code for code in codes if code not in completed]
        print(
            f"CODES total={len(codes)} completed={len(completed)} pending={len(pending)}",
            flush=True,
        )
        chunks = [
            pending[offset : offset + args.chunk_size]
            for offset in range(0, len(pending), args.chunk_size)
        ]
        for chunk in chunks:
            result = {"rows": [], "successful": [], "failures": []}
            for code in chunk:
                try:
                    rows = collect_code(code, args.start, args.end, exit_end)
                    result["rows"].extend(rows)
                    result["successful"].append(code)
                except Exception as exc:  # noqa: BLE001
                    result["failures"].append(
                        {"code": code, "error": f"{type(exc).__name__}: {exc}"}
                    )
            persist_result(
                result, state, state_path, parts_dir, args, exit_end, started
            )
        print("RESULT=" + json.dumps(state, ensure_ascii=False), flush=True)
    finally:
        bs.logout()


if __name__ == "__main__":
    main()
