#!/usr/bin/env python3
"""采集阶段 C 指定区间的 5 分钟基础筛选数据。

按冻结区间独立运行，输出可恢复的日线、5 分钟聚合特征、历史股票池与行业快照。
本脚本不验证 1 分钟尾盘结构，也不产生策略收益结论。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import math
import pathlib
import socket
import signal
import time
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import baostock as bs
import pyarrow as pa
import pyarrow.parquet as pq


MAINBOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
EXPECTED_5M_TIMES = tuple(
    [f"09{minute:02d}" for minute in range(35, 60, 5)]
    + [f"10{minute:02d}" for minute in range(0, 60, 5)]
    + [f"11{minute:02d}" for minute in range(0, 31, 5)]
    + [f"13{minute:02d}" for minute in range(5, 60, 5)]
    + [f"14{minute:02d}" for minute in range(0, 60, 5)]
    + ["1500"]
)
EXPECTED_5M_TIMES_1430 = tuple(value for value in EXPECTED_5M_TIMES if value <= "1430")
RECENT_WINDOWS = (10, 15, 20, 30)
MA_WINDOWS = (20, 60, 90, 120)
STREAK_WINDOWS = (2, 3, 4, 5)
NETWORK_TIMEOUT_SECONDS = 45
QUERY_DEADLINE_SECONDS = 180
INITIAL_LOGIN_ATTEMPTS = 6
INITIAL_LOGIN_BACKOFF_SECONDS = 30
BLACKLIST_ERROR_CODE = "10001011"
TURNOVER_HALF_UNIT_PCT = 0.00005
socket.setdefaulttimeout(NETWORK_TIMEOUT_SECONDS)


class BaostockSessionError(RuntimeError):
    """Baostock 会话已无法通过重新登录恢复。"""


@contextlib.contextmanager
def hard_deadline(seconds: int):
    if not hasattr(signal, "SIGALRM"):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def timeout_handler(_signum, _frame):
        raise TimeoutError(f"接口调用超过 {seconds} 秒硬截止")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--chunk-size", type=int, default=5)
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


def finite_positive(value: float) -> bool:
    return math.isfinite(value) and value > 0


def price_limit(preclose: float, ratio: float) -> float:
    if not finite_positive(preclose):
        return math.nan
    value = Decimal(str(preclose)) * Decimal(str(1.0 + ratio))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def save_json(path: pathlib.Path, value: dict | list) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_table(rows: list[dict], path: pathlib.Path) -> None:
    if not rows:
        return
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def iterate_result(result, label: str) -> list[list[str]]:
    rows: list[list[str]] = []
    while result.error_code == "0" and result.next():
        rows.append(result.get_row_data())
    if result.error_code != "0":
        raise RuntimeError(f"{label}: {result.error_code} {result.error_msg}")
    return rows


def relogin() -> None:
    try:
        with hard_deadline(10):
            bs.logout()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(1.0)
    with hard_deadline(30):
        login = bs.login()
    if login.error_code != "0":
        error = f"Baostock relogin: {login.error_code} {login.error_msg}"
        if login.error_code == BLACKLIST_ERROR_CODE:
            raise BaostockSessionError(error)
        raise RuntimeError(error)


def initial_login() -> None:
    errors: list[str] = []
    for attempt in range(INITIAL_LOGIN_ATTEMPTS):
        try:
            with hard_deadline(30):
                login = bs.login()
            if login.error_code == "0":
                return
            errors.append(f"{login.error_code} {login.error_msg}")
            if login.error_code == BLACKLIST_ERROR_CODE:
                raise BaostockSessionError("Baostock login: " + errors[-1])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
        if attempt + 1 < INITIAL_LOGIN_ATTEMPTS:
            delay = min(INITIAL_LOGIN_BACKOFF_SECONDS * (attempt + 1), 120)
            print(
                f"LOGIN_RETRY attempt={attempt + 1}/{INITIAL_LOGIN_ATTEMPTS} "
                f"delay_seconds={delay}",
                flush=True,
            )
            time.sleep(delay)
    raise BaostockSessionError("Baostock login: " + " | ".join(errors))


def retry_query(factory, label: str, attempts: int = 3) -> list[list[str]]:
    errors: list[str] = []
    relogin_failed = False
    for attempt in range(attempts):
        try:
            with hard_deadline(QUERY_DEADLINE_SECONDS):
                return iterate_result(factory(), label)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt + 1 < attempts:
                try:
                    relogin()
                except BaostockSessionError as relogin_exc:
                    errors.append(
                        f"relogin {type(relogin_exc).__name__}: {relogin_exc}"
                    )
                    raise BaostockSessionError(
                        f"{label}: {' | '.join(errors)}"
                    ) from relogin_exc
                except Exception as relogin_exc:  # noqa: BLE001
                    relogin_failed = True
                    errors.append(
                        f"relogin {type(relogin_exc).__name__}: {relogin_exc}"
                    )
                time.sleep(float(attempt + 1))
    error_type = BaostockSessionError if relogin_failed else RuntimeError
    raise error_type(f"{label}: {' | '.join(errors)}")


def trade_dates(start: str, end: str) -> list[str]:
    rows = retry_query(
        lambda: bs.query_trade_dates(start_date=start, end_date=end),
        f"trade_dates {start}..{end}",
    )
    return [date for date, is_trading in rows if is_trading == "1"]


def next_trade_date(end: str) -> str:
    final = dt.date.fromisoformat(end)
    candidates = trade_dates(end, (final + dt.timedelta(days=14)).isoformat())
    later = [value for value in candidates if value > end]
    if not later:
        raise RuntimeError(f"无法找到 {end} 后的下一交易日")
    return later[0]


def snapshot_dates(dates: list[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for date in dates:
        month = date[:7]
        if month not in seen:
            selected.append(date)
            seen.add(month)
    if dates and dates[-1] not in selected:
        selected.append(dates[-1])
    return selected


def collect_context(dates: list[str]) -> tuple[list[str], list[dict], list[dict]]:
    codes: set[str] = set()
    universe: list[dict] = []
    industry: list[dict] = []
    for date in snapshot_dates(dates):
        stocks = retry_query(lambda: bs.query_all_stock(day=date), f"all_stock {date}")
        for code, trade_status, name in stocks:
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
        industries = retry_query(
            lambda: bs.query_stock_industry(date=date), f"industry {date}"
        )
        for update_date, code, name, industry_name, classification in industries:
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
    return sorted(codes), universe, industry


def month_ranges(start: str, end: str) -> list[tuple[str, str]]:
    current = dt.date.fromisoformat(start).replace(day=1)
    final = dt.date.fromisoformat(end)
    ranges: list[tuple[str, str]] = []
    while current <= final:
        next_month = (
            dt.date(current.year + 1, 1, 1)
            if current.month == 12
            else dt.date(current.year, current.month + 1, 1)
        )
        ranges.append(
            (
                max(current, dt.date.fromisoformat(start)).isoformat(),
                min(next_month - dt.timedelta(days=1), final).isoformat(),
            )
        )
        current = next_month
    return ranges


def query_daily(code: str, start: str, end: str) -> list[dict]:
    fields = (
        "date,code,open,high,low,close,preclose,volume,amount,turn,"
        "tradestatus,pctChg,isST"
    )
    raw_rows = retry_query(
        lambda: bs.query_history_k_data_plus(
            code,
            fields,
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="3",
        ),
        f"daily {code} {start}..{end}",
    )
    names = fields.split(",")
    rows: list[dict] = []
    for values in raw_rows:
        raw = dict(zip(names, values))
        rows.append(
            {
                "code": code,
                "date": raw["date"],
                "open": as_float(raw["open"]),
                "high": as_float(raw["high"]),
                "low": as_float(raw["low"]),
                "close": as_float(raw["close"]),
                "preclose": as_float(raw["preclose"]),
                "volume": as_float(raw["volume"]),
                "amount": as_float(raw["amount"]),
                "turnover_full_day": as_float(raw["turn"]),
                "trade_status": int(raw["tradestatus"] or 0),
                "pct": as_float(raw["pctChg"]),
                "is_st": raw["isST"] == "1",
            }
        )
    return rows


def query_5m(code: str, start: str, end: str) -> list[list[str]]:
    fields = "date,time,code,open,high,low,close,volume,amount,adjustflag"
    rows: list[list[str]] = []
    for segment_start, segment_end in month_ranges(start, end):
        rows.extend(
            retry_query(
                lambda segment_start=segment_start, segment_end=segment_end: (
                    bs.query_history_k_data_plus(
                        code,
                        fields,
                        start_date=segment_start,
                        end_date=segment_end,
                        frequency="5",
                        adjustflag="3",
                    )
                ),
                f"5m {code} {segment_start}..{segment_end}",
            )
        )
    return rows


def daily_is_valid(row: dict | None) -> bool:
    return bool(
        row
        and row["trade_status"] == 1
        and finite_positive(row["volume"])
        and math.isfinite(row["pct"])
    )


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else math.nan


def stddev(values: list[float]) -> float:
    if len(values) < 2:
        return math.nan
    average = mean(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / (len(values) - 1))


def build_daily_features(
    rows: list[dict], calendar: list[str], signal_start: str, exit_end: str
) -> tuple[dict[str, dict], list[dict]]:
    by_date = {row["date"]: row for row in rows}
    calendar_index = {date: index for index, date in enumerate(calendar)}
    first_observed = min((calendar_index[d] for d in by_date if d in calendar_index), default=None)

    above_ma: dict[int, dict[str, bool | None]] = {window: {} for window in MA_WINDOWS}
    for window in MA_WINDOWS:
        for index, date in enumerate(calendar):
            history = calendar[index - window + 1 : index + 1] if index >= window - 1 else []
            history_rows = [by_date.get(item) for item in history]
            if len(history_rows) != window or not all(daily_is_valid(item) for item in history_rows):
                above_ma[window][date] = None
            else:
                volumes = [item["volume"] for item in history_rows if item is not None]
                above_ma[window][date] = by_date[date]["volume"] > mean(volumes)

    features: dict[str, dict] = {}
    daily_output: list[dict] = []
    for date in calendar:
        if not (signal_start <= date <= exit_end):
            continue
        row = by_date.get(date)
        if row is None:
            continue
        index = calendar_index[date]
        previous_date = calendar[index - 1] if index > 0 else ""
        previous_row = by_date.get(previous_date)
        output = dict(row)
        output["listing_market_days_prior"] = (
            index - first_observed if first_observed is not None and index >= first_observed else None
        )
        output["is_resume_day"] = daily_is_valid(row) and index > 0 and not daily_is_valid(previous_row)
        for window in RECENT_WINDOWS:
            history_dates = calendar[index - window : index] if index >= window else []
            history_rows = [by_date.get(item) for item in history_dates]
            complete = len(history_rows) == window and all(daily_is_valid(item) for item in history_rows)
            output[f"recent_{window}_complete"] = complete
            output[f"recent_{window}_max_pct"] = (
                max(item["pct"] for item in history_rows if item is not None)
                if complete
                else math.nan
            )
        previous5_dates = calendar[index - 5 : index] if index >= 5 else []
        previous5_rows = [by_date.get(item) for item in previous5_dates]
        previous5_complete = len(previous5_rows) == 5 and all(
            daily_is_valid(item) for item in previous5_rows
        )
        output["previous5_complete"] = previous5_complete
        output["previous5_mean_volume"] = (
            mean([item["volume"] for item in previous5_rows if item is not None])
            if previous5_complete
            else math.nan
        )
        previous20_dates = calendar[index - 20 : index] if index >= 20 else []
        previous20_rows = [by_date.get(item) for item in previous20_dates]
        previous20_complete = len(previous20_rows) == 20 and all(
            daily_is_valid(item) for item in previous20_rows
        )
        output["previous20_complete"] = previous20_complete
        output["previous20_volatility"] = (
            stddev([item["pct"] / 100.0 for item in previous20_rows if item is not None])
            if previous20_complete
            else math.nan
        )
        output["previous20_mean_amount"] = (
            mean([item["amount"] for item in previous20_rows if item is not None])
            if previous20_complete
            else math.nan
        )
        for ma_window in MA_WINDOWS:
            for streak in STREAK_WINDOWS:
                prior_dates = calendar[index - streak : index] if index >= streak else []
                flags = [above_ma[ma_window].get(item) for item in prior_dates]
                complete = len(flags) == streak and all(flag is not None for flag in flags)
                output[f"volume_ma{ma_window}_d{streak}_complete"] = complete
                output[f"volume_ma{ma_window}_d{streak}_ok"] = complete and all(flags)
        daily_output.append(output)
        features[date] = output
    return features, daily_output


def intraday_aggregates(rows: list[list[str]]) -> dict[str, dict]:
    grouped: dict[str, list[list[str]]] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(row)
    output: dict[str, dict] = {}
    for date, bars in grouped.items():
        source_times = [row[1][8:12] for row in bars]
        source_out_of_order = sum(
            current < previous for previous, current in zip(source_times, source_times[1:])
        )
        bars.sort(key=lambda item: item[1])
        times = [row[1][8:12] for row in bars]
        time_set = set(times)
        times1430 = [value for value in times if value <= "1430"]
        time1430_set = set(times1430)
        cumulative_volume = 0.0
        cumulative_amount = 0.0
        price1430 = math.nan
        volume1430 = math.nan
        amount1430 = math.nan
        strength_count = 0
        above_vwap_count = 0
        entry: dict = {}
        first_exit: dict = {}
        exit_volume = 0.0
        exit_amount = 0.0
        exit_high = math.nan
        exit_low = math.nan
        for raw in bars:
            tm = raw[1][8:12]
            high = as_float(raw[4])
            low = as_float(raw[5])
            close = as_float(raw[6])
            volume = as_float(raw[7])
            amount = as_float(raw[8])
            volume = volume if math.isfinite(volume) else 0.0
            amount = amount if math.isfinite(amount) else 0.0
            cumulative_volume += volume
            cumulative_amount += amount
            if tm <= "1430":
                price1430 = close
                volume1430 = cumulative_volume
                amount1430 = cumulative_amount
            if "1000" <= tm <= "1430":
                strength_count += 1
                current_vwap = cumulative_amount / cumulative_volume if cumulative_volume > 0 else math.nan
                if math.isfinite(close) and math.isfinite(current_vwap) and close >= current_vwap:
                    above_vwap_count += 1
            if tm == "1435":
                entry = {
                    "entry_next_5m_vwap": amount / volume if volume > 0 else math.nan,
                    "entry_next_5m_volume": volume,
                    "entry_next_5m_amount": amount,
                    "entry_next_5m_high": high,
                    "entry_next_5m_low": low,
                }
            if tm == "0935":
                first_exit = {
                    "exit_first_5m_vwap": amount / volume if volume > 0 else math.nan,
                    "exit_first_5m_volume": volume,
                    "exit_first_5m_high": high,
                    "exit_first_5m_low": low,
                }
            if "0935" <= tm <= "1000":
                exit_volume += volume
                exit_amount += amount
                exit_high = high if not math.isfinite(exit_high) else max(exit_high, high)
                exit_low = low if not math.isfinite(exit_low) else min(exit_low, low)
        exact_1430 = (
            len(times1430) == len(EXPECTED_5M_TIMES_1430)
            and time1430_set == set(EXPECTED_5M_TIMES_1430)
            and len(times1430) == len(time1430_set)
            and source_out_of_order == 0
        )
        output[date] = {
            "bar_count": len(times),
            "distinct_bar_count": len(time_set),
            "source_out_of_order_count": source_out_of_order,
            "bar_count1430": len(times1430),
            "distinct_bar_count1430": len(time1430_set),
            "duplicate_bar_count1430": len(times1430) - len(time1430_set),
            "unexpected_bar_count1430": len(time1430_set - set(EXPECTED_5M_TIMES_1430)),
            "missing_expected_bar_count1430": len(set(EXPECTED_5M_TIMES_1430) - time1430_set),
            "has_1430_bar": times.count("1430") == 1,
            "exact_1430_complete": exact_1430,
            "price1430": price1430,
            "cum_volume1430": volume1430,
            "cum_amount1430": amount1430,
            "vwap1430": amount1430 / volume1430 if finite_positive(volume1430) else math.nan,
            "full_day_5m_volume": cumulative_volume,
            "full_day_5m_amount": cumulative_amount,
            "strength_5m_count": strength_count,
            "above_vwap_5m_count": above_vwap_count,
            "above_vwap_5m_ratio": above_vwap_count / strength_count if strength_count else math.nan,
            **entry,
            **first_exit,
            "exit_to_1000_vwap": exit_amount / exit_volume if exit_volume > 0 else math.nan,
            "exit_to_1000_volume": exit_volume,
            "exit_to_1000_high": exit_high,
            "exit_to_1000_low": exit_low,
        }
    return output


def exit_status(day: dict | None, bar: dict, prefix: str) -> tuple[str, bool]:
    if day is None:
        return "EXIT_DAILY_MISSING", False
    if day["trade_status"] != 1:
        return "EXIT_SUSPENDED", False
    vwap = bar.get(f"{prefix}_vwap", math.nan)
    high = bar.get(f"{prefix}_high", math.nan)
    volume = bar.get(f"{prefix}_volume", math.nan)
    lower = price_limit(day["preclose"], -0.05 if day["is_st"] else -0.10)
    if finite_positive(vwap) and finite_positive(volume) and math.isfinite(high) and high > lower + 0.000001:
        return "EXECUTABLE_5M_BAR_MODEL", True
    if math.isfinite(day["high"]) and math.isfinite(lower) and day["high"] <= lower + 0.000001:
        return "LIMIT_DOWN_LOCKED", False
    return "EXIT_WINDOW_MISSING", False


def build_feature_rows(
    code: str,
    start: str,
    end: str,
    calendar: list[str],
    daily_features: dict[str, dict],
    intraday: dict[str, dict],
) -> list[dict]:
    index = {date: position for position, date in enumerate(calendar)}
    rows: list[dict] = []
    for date in calendar:
        if not (start <= date <= end):
            continue
        day = daily_features.get(date)
        bar = intraday.get(date)
        if day is None or bar is None:
            continue
        position = index[date]
        next_date = calendar[position + 1] if position + 1 < len(calendar) else ""
        next_day = daily_features.get(next_date)
        next_bar = intraday.get(next_date, {})
        preclose = day["preclose"]
        price1430 = bar["price1430"]
        volume1430 = bar["cum_volume1430"]
        daily_volume = day["volume"]
        full_turnover = day["turnover_full_day"]
        float_shares = (
            daily_volume / (full_turnover / 100.0)
            if finite_positive(daily_volume) and finite_positive(full_turnover)
            else math.nan
        )
        turnover_point = (
            volume1430 / float_shares * 100.0
            if finite_positive(volume1430) and finite_positive(float_shares)
            else math.nan
        )
        turnover_lower = (
            volume1430 / daily_volume * max(full_turnover - TURNOVER_HALF_UNIT_PCT, 0.0)
            if finite_positive(volume1430) and finite_positive(daily_volume) and finite_positive(full_turnover)
            else math.nan
        )
        turnover_upper = (
            volume1430 / daily_volume * (full_turnover + TURNOVER_HALF_UNIT_PCT)
            if finite_positive(volume1430) and finite_positive(daily_volume) and finite_positive(full_turnover)
            else math.nan
        )
        previous5_volume = day["previous5_mean_volume"]
        volume_ratio = (
            (volume1430 / 210.0) / (previous5_volume / 240.0)
            if finite_positive(volume1430) and finite_positive(previous5_volume)
            else math.nan
        )
        ret1430 = (
            (price1430 / preclose - 1.0) * 100.0
            if finite_positive(price1430) and finite_positive(preclose)
            else math.nan
        )
        upper = price_limit(preclose, 0.05 if day["is_st"] else 0.10)
        entry_vwap = bar.get("entry_next_5m_vwap", math.nan)
        entry_low = bar.get("entry_next_5m_low", math.nan)
        entry_volume = bar.get("entry_next_5m_volume", math.nan)
        if not finite_positive(entry_vwap) or not finite_positive(entry_volume):
            entry_status = "ENTRY_WINDOW_MISSING"
            entry_executable = False
        elif math.isfinite(entry_low) and entry_low >= upper - 0.000001:
            entry_status = "LIMIT_UP_LOCKED"
            entry_executable = False
        else:
            entry_status = "EXECUTABLE_5M_BAR_MODEL"
            entry_executable = True
        first_status, first_executable = exit_status(next_day, next_bar, "exit_first_5m")
        window_status, window_executable = exit_status(next_day, next_bar, "exit_to_1000")
        full_day_volume_relative_error = (
            abs(bar["full_day_5m_volume"] - daily_volume) / daily_volume
            if finite_positive(bar["full_day_5m_volume"]) and finite_positive(daily_volume)
            else math.nan
        )
        minute_daily_volume_conflict = (
            finite_positive(volume1430)
            and finite_positive(daily_volume)
            and volume1430 > daily_volume + 1.0
        )
        signal = {
            key: value
            for key, value in day.items()
            if key
            not in {
                "open",
                "high",
                "low",
                "close",
                "amount",
                "pct",
                "turnover_full_day",
            }
        }
        rows.append(
            {
                "code": code,
                "date": date,
                **bar,
                **signal,
                "ret1430": ret1430,
                "volume_ratio1430": volume_ratio,
                "historical_float_shares": float_shares,
                "turnover1430": turnover_point,
                "turnover1430_lower": turnover_lower,
                "turnover1430_upper": turnover_upper,
                "float_market_cap1430": float_shares * price1430 if finite_positive(float_shares) and finite_positive(price1430) else math.nan,
                "full_day_volume_relative_error": full_day_volume_relative_error,
                "minute_daily_volume_conflict": minute_daily_volume_conflict,
                "entry_upper_limit": upper,
                "entry_status": entry_status,
                "entry_executable": entry_executable,
                "next_market_date": next_date,
                "next_exit_first_5m_vwap": next_bar.get("exit_first_5m_vwap", math.nan),
                "next_exit_to_1000_vwap": next_bar.get("exit_to_1000_vwap", math.nan),
                "next_exit_first_5m_status": first_status,
                "next_exit_to_1000_status": window_status,
                "next_exit_first_5m_executable": first_executable,
                "next_exit_to_1000_executable": window_executable,
            }
        )
    return rows


def collect_code(
    code: str, start: str, end: str, exit_end: str, full_calendar: list[str]
) -> tuple[list[dict], list[dict]]:
    lookback = (dt.date.fromisoformat(start) - dt.timedelta(days=520)).isoformat()
    daily_rows = query_daily(code, lookback, exit_end)
    daily_features, daily_output = build_daily_features(
        daily_rows, full_calendar, start, exit_end
    )
    intraday = intraday_aggregates(query_5m(code, start, exit_end))
    features = build_feature_rows(
        code, start, end, full_calendar, daily_features, intraday
    )
    return daily_output, features


def load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"completed_codes": [], "failures": [], "parts": []}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    if args.chunk_size < 1:
        raise SystemExit("--chunk-size 必须大于等于 1")
    start_date = dt.date.fromisoformat(args.start)
    end_date = dt.date.fromisoformat(args.end)
    if start_date > end_date:
        raise SystemExit("--start 不能晚于 --end")
    output = pathlib.Path(args.output).expanduser().resolve()
    state_path = output / "state.json"
    if output.exists() and not args.resume:
        raise SystemExit(f"输出目录已存在；继续请使用 --resume：{output}")
    output.mkdir(parents=True, exist_ok=True)
    features_dir = output / "features"
    daily_dir = output / "daily"
    features_dir.mkdir(exist_ok=True)
    daily_dir.mkdir(exist_ok=True)

    initial_login()
    started = time.time()
    try:
        exit_end = next_trade_date(args.end)
        lookback = (start_date - dt.timedelta(days=520)).isoformat()
        full_calendar = trade_dates(lookback, exit_end)
        signal_calendar = [value for value in full_calendar if args.start <= value <= exit_end]
        if not (output / "universe.parquet").exists():
            codes, universe, industry = collect_context(signal_calendar)
            if args.limit > 0:
                codes = codes[: args.limit]
                selected = set(codes)
                universe = [row for row in universe if row["code"] in selected]
                industry = [row for row in industry if row["code"] in selected]
            write_table(universe, output / "universe.parquet")
            write_table(industry, output / "industry.parquet")
            save_json(output / "codes.json", codes)
            pq.write_table(
                pa.Table.from_pylist([{"date": value} for value in full_calendar]),
                output / "trade_calendar.parquet",
                compression="zstd",
            )
        else:
            codes = json.loads((output / "codes.json").read_text(encoding="utf-8"))
        state = load_state(state_path)
        completed = set(state["completed_codes"])
        pending = [code for code in codes if code not in completed]
        print(
            f"CODES total={len(codes)} completed={len(completed)} pending={len(pending)}",
            flush=True,
        )
        for offset in range(0, len(pending), args.chunk_size):
            chunk = pending[offset : offset + args.chunk_size]
            feature_rows: list[dict] = []
            daily_rows: list[dict] = []
            successful: list[str] = []
            failures: list[dict] = []
            fatal_session_error: BaostockSessionError | None = None
            for code in chunk:
                try:
                    code_daily, code_features = collect_code(
                        code, args.start, args.end, exit_end, full_calendar
                    )
                    daily_rows.extend(code_daily)
                    feature_rows.extend(code_features)
                    successful.append(code)
                except BaostockSessionError as exc:
                    failures.append(
                        {"code": code, "error": f"{type(exc).__name__}: {exc}"}
                    )
                    fatal_session_error = exc
                    break
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        {"code": code, "error": f"{type(exc).__name__}: {exc}"}
                    )
            part_index = len(state["parts"])
            feature_path = features_dir / f"part-{part_index:05d}.parquet"
            daily_path = daily_dir / f"part-{part_index:05d}.parquet"
            write_table(feature_rows, feature_path)
            write_table(daily_rows, daily_path)
            state["parts"].append(
                {
                    "index": part_index,
                    "codes": successful,
                    "feature_path": str(feature_path) if feature_rows else None,
                    "feature_rows": len(feature_rows),
                    "daily_path": str(daily_path) if daily_rows else None,
                    "daily_rows": len(daily_rows),
                }
            )
            state["completed_codes"].extend(successful)
            state["failures"].extend(failures)
            state["parameters"] = vars(args)
            state["exit_end"] = exit_end
            state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            state["elapsed_seconds_this_run"] = round(time.time() - started, 3)
            save_json(state_path, state)
            print(
                f"CHUNK completed={len(successful)} failed={len(failures)} "
                f"total_completed={len(state['completed_codes'])}",
                flush=True,
            )
            if fatal_session_error is not None:
                raise fatal_session_error
        unresolved = sorted(set(codes) - set(state["completed_codes"]))
        state["unresolved_codes"] = unresolved
        state["status"] = "COMPLETE" if not unresolved else "INCOMPLETE"
        state["elapsed_seconds_this_run"] = round(time.time() - started, 3)
        save_json(state_path, state)
        print(
            "RESULT="
            + json.dumps(
                {
                    "status": state["status"],
                    "codes": len(codes),
                    "completed": len(set(state["completed_codes"])),
                    "unresolved": len(unresolved),
                    "parts": len(state["parts"]),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        try:
            with hard_deadline(10):
                bs.logout()
        except Exception as exc:  # noqa: BLE001
            print(f"LOGOUT_WARNING={type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
