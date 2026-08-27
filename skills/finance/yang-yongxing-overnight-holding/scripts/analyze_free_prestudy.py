#!/usr/bin/env python3
"""运行5分钟近似预研和近期1分钟结构复核。"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--end", default="2026-08-19")
    parser.add_argument("--one-minute-start", default="2026-08-11")
    return parser.parse_args()


def number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def load_spot(path: pathlib.Path) -> pd.DataFrame:
    rows = json.loads(path.read_text(encoding="utf-8"))
    output = []
    for row in rows:
        price = number(row.get("trade"))
        nmc_wan = number(row.get("nmc"))
        if not math.isfinite(price) or price <= 0 or not math.isfinite(nmc_wan) or nmc_wan <= 0:
            continue
        output.append(
            {
                "code": str(row.get("code", "")),
                "current_name": str(row.get("name", "")),
                "current_price": price,
                "float_shares_approx": nmc_wan * 10000.0 / price,
            }
        )
    return pd.DataFrame(output).drop_duplicates("code", keep="last")


def latest_snapshot_maps(frame: pd.DataFrame, value_column: str):
    frame = frame.sort_values(["date", "code"])
    snapshots = []
    for date, group in frame.groupby("date", sort=True):
        snapshots.append((date, dict(zip(group["code"], group[value_column]))))
    return snapshots


def map_snapshot_value(date: str, code: str, snapshots, default="未知"):
    selected = None
    for snapshot_date, mapping in snapshots:
        if snapshot_date <= date:
            selected = mapping
        else:
            break
    return default if selected is None else selected.get(code, default)


def daily_features(connection: duckdb.DuckDBPyConnection, daily_path: pathlib.Path) -> pd.DataFrame:
    query = """
    WITH base AS (
      SELECT
        code, date, open, high, low, close, volume,
        lag(close) OVER (PARTITION BY code ORDER BY date) AS preclose,
        CASE WHEN lag(close) OVER (PARTITION BY code ORDER BY date) > 0
          THEN (close / lag(close) OVER (PARTITION BY code ORDER BY date) - 1) * 100 END AS pct,
        avg(volume) OVER (
          PARTITION BY code ORDER BY date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
        ) AS ma120,
        count(*) OVER (
          PARTITION BY code ORDER BY date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
        ) AS ma120_count
      FROM read_parquet(?)
    ), marked AS (
      SELECT *, CASE WHEN ma120_count = 120 AND volume > ma120 THEN 1 ELSE 0 END AS volume_above_ma120
      FROM base
    )
    SELECT
      code, date, preclose,
      avg(volume) OVER (
        PARTITION BY code ORDER BY date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
      ) AS prev5_volume,
      count(volume) OVER (
        PARTITION BY code ORDER BY date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
      ) AS prev5_count,
      max(CASE WHEN pct >= 5.0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY code ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS recent_strong,
      count(pct) OVER (
        PARTITION BY code ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS recent_count,
      min(volume_above_ma120) OVER (
        PARTITION BY code ORDER BY date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
      ) AS volume3_ok,
      count(volume_above_ma120) OVER (
        PARTITION BY code ORDER BY date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
      ) AS volume3_count
    FROM marked
    """
    return connection.execute(query, [str(daily_path)]).df()


def intraday_features(
    connection: duckdb.DuckDBPyConnection,
    bars_path: pathlib.Path,
    daily: pd.DataFrame,
    spot: pd.DataFrame,
    start: str,
    end: str,
) -> pd.DataFrame:
    connection.register("daily_features_df", daily)
    connection.register("spot_df", spot)
    query = """
    WITH bars AS (
      SELECT
        code,
        substr(timestamp, 1, 10) AS date,
        substr(timestamp, 12, 5) AS tm,
        timestamp,
        close, volume, amount,
        sum(volume) OVER (
          PARTITION BY code, substr(timestamp, 1, 10) ORDER BY timestamp
        ) AS cum_volume,
        sum(amount) OVER (
          PARTITION BY code, substr(timestamp, 1, 10) ORDER BY timestamp
        ) AS cum_amount
      FROM read_parquet(?)
      WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
    ), agg AS (
      SELECT
        code, date,
        arg_max(close, timestamp) FILTER (WHERE tm <= '14:30') AS price1430,
        max(cum_volume) FILTER (WHERE tm <= '14:30') AS cum_volume1430,
        max(cum_amount) FILTER (WHERE tm <= '14:30') AS cum_amount1430,
        count(*) FILTER (WHERE tm BETWEEN '10:00' AND '14:30') AS strength_count,
        sum(CASE WHEN tm BETWEEN '10:00' AND '14:30'
          AND cum_volume > 0 AND close >= cum_amount / cum_volume THEN 1 ELSE 0 END) AS above_vwap_count,
        count(*) AS bar_count
      FROM bars
      GROUP BY code, date
    )
    SELECT
      a.*,
      d.preclose, d.prev5_volume, d.prev5_count, d.recent_strong, d.recent_count,
      d.volume3_ok, d.volume3_count,
      s.current_name, s.float_shares_approx
    FROM agg a
    LEFT JOIN daily_features_df d USING (code, date)
    LEFT JOIN spot_df s USING (code)
    """
    frame = connection.execute(query, [str(bars_path), start, end]).df()
    frame["vwap1430"] = frame["cum_amount1430"] / frame["cum_volume1430"]
    frame["ret1430"] = (frame["price1430"] / frame["preclose"] - 1.0) * 100.0
    frame["above_vwap_ratio"] = frame["above_vwap_count"] / frame["strength_count"]
    frame["turnover1430"] = frame["cum_volume1430"] / frame["float_shares_approx"] * 100.0
    frame["volume_ratio1430"] = (frame["cum_volume1430"] / 210.0) / (
        frame["prev5_volume"] / 240.0
    )
    frame["amount_percentile"] = frame.groupby("date")["cum_amount1430"].rank(
        method="max", pct=True
    )
    return frame


def add_sector_and_checks(
    frame: pd.DataFrame, industry_snapshots, st_snapshots
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = frame.copy()
    frame["industry"] = [
        map_snapshot_value(date, code, industry_snapshots)
        for date, code in zip(frame["date"], frame["code"])
    ]
    frame["historical_is_st"] = [
        bool(map_snapshot_value(date, code, st_snapshots, default=False))
        for date, code in zip(frame["date"], frame["code"])
    ]
    valid = (
        frame["preclose"].gt(0)
        & frame["price1430"].gt(0)
        & frame["cum_amount1430"].gt(0)
        & frame["strength_count"].gt(0)
        & frame["prev5_count"].eq(5)
        & frame["recent_count"].ge(20)
        & frame["volume3_count"].eq(3)
        & frame["float_shares_approx"].gt(0)
        & frame["industry"].ne("未知")
        & ~frame["historical_is_st"]
    )
    frame["data_valid"] = valid

    stats_rows = []
    for (date, industry), group in frame[valid].groupby(["date", "industry"]):
        if len(group) < 5:
            continue
        stats_rows.append(
            {
                "date": date,
                "industry": industry,
                "count": len(group),
                "median_ret": float(group["ret1430"].median()),
                "positive_breadth": float((group["ret1430"] > 0).mean()),
                "above_vwap_breadth": float((group["price1430"] >= group["vwap1430"]).mean()),
                "strong_count": int((group["ret1430"] >= 3.0).sum()),
            }
        )
    stats = pd.DataFrame(stats_rows)
    if stats.empty:
        frame["hot_sector"] = False
        return frame, stats

    stats["sector_cutoff"] = np.nan
    stats["hot_sector"] = False
    for date, indexes in stats.groupby("date").groups.items():
        values = sorted(stats.loc[indexes, "median_ret"].tolist())
        cutoff = values[math.floor(len(values) * 0.75)]
        stats.loc[indexes, "sector_cutoff"] = cutoff
        stats.loc[indexes, "hot_sector"] = (
            (stats.loc[indexes, "median_ret"] >= cutoff)
            & (stats.loc[indexes, "positive_breadth"] >= 0.55)
            & (stats.loc[indexes, "above_vwap_breadth"] >= 0.55)
            & (stats.loc[indexes, "strong_count"] >= 2)
        )

    frame = frame.merge(
        stats[
            [
                "date",
                "industry",
                "median_ret",
                "positive_breadth",
                "above_vwap_breadth",
                "strong_count",
                "hot_sector",
            ]
        ],
        on=["date", "industry"],
        how="left",
    )
    frame["hot_sector"] = frame["hot_sector"].fillna(False)
    frame["check_hot_sector"] = frame["data_valid"] & frame["hot_sector"]
    frame["check_relative_strength"] = (
        frame["data_valid"]
        & (frame["ret1430"] > np.maximum(0.0, frame["median_ret"].fillna(np.inf)))
        & (frame["ret1430"] < 8.5)
    )
    frame["check_turnover"] = frame["data_valid"] & frame["turnover1430"].between(5.0, 10.0)
    frame["check_amount"] = frame["data_valid"] & frame["amount_percentile"].ge(0.75)
    frame["check_above_vwap"] = (
        frame["data_valid"]
        & frame["above_vwap_ratio"].ge(0.70)
        & frame["price1430"].ge(frame["vwap1430"])
    )
    frame["check_volume_ratio"] = frame["data_valid"] & frame["volume_ratio1430"].gt(1.0)
    frame["check_recent_strong"] = frame["data_valid"] & frame["recent_strong"].eq(1)
    frame["check_volume3"] = frame["data_valid"] & frame["volume3_ok"].eq(1)
    check_columns = [
        "check_hot_sector",
        "check_relative_strength",
        "check_turnover",
        "check_amount",
        "check_above_vwap",
        "check_volume_ratio",
        "check_recent_strong",
        "check_volume3",
    ]
    frame["base_candidate"] = frame[check_columns].all(axis=1)
    return frame, stats


def load_candidate_bars(connection, bars_path: pathlib.Path, candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    keys = candidates[["code", "date"]].drop_duplicates()
    connection.register("candidate_keys", keys)
    query = """
      SELECT b.*
      FROM read_parquet(?) b
      JOIN candidate_keys k
        ON b.code = k.code AND substr(b.timestamp, 1, 10) = k.date
      ORDER BY b.code, b.timestamp
    """
    return connection.execute(query, [str(bars_path)]).df()


def prepare_group(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values("timestamp").copy()
    group["date"] = group["timestamp"].str[:10]
    group["tm"] = group["timestamp"].str[11:16]
    group["cum_volume"] = group["volume"].cumsum()
    group["cum_amount"] = group["amount"].cumsum()
    group["vwap"] = group["cum_amount"] / group["cum_volume"]
    group["bar_vwap"] = group["amount"] / group["volume"].replace(0, np.nan)
    return group


def max_consecutive_below(frame: pd.DataFrame) -> int:
    best = current = 0
    for below in (frame["close"] < frame["vwap"]).tolist():
        if below:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


@dataclass
class TailResult:
    ok: bool
    reason: str
    confirm_time: str | None = None
    entry_time: str | None = None
    entry_price: float | None = None
    shrink_ratio: float | None = None


def tail_5m(group: pd.DataFrame) -> TailResult:
    group = prepare_group(group)
    before = group[group["tm"].between("13:30", "14:25")]
    tail = group[group["tm"].between("14:30", "14:50")].reset_index(drop=True)
    if before.empty or len(tail) < 5:
        return TailResult(False, "5分钟数据不足")
    prior_high = before["close"].max()
    peak_i = int(tail["close"].idxmax())
    if peak_i < 1 or peak_i > len(tail) - 3 or tail.loc[peak_i, "close"] <= prior_high:
        return TailResult(False, "未形成可回踩突破")
    after_peak = tail.iloc[peak_i + 1 :]
    trough_i = int(after_peak["close"].idxmin())
    if trough_i > len(tail) - 2:
        return TailResult(False, "回踩过晚")
    trough = tail.loc[trough_i]
    rally = tail.iloc[: peak_i + 1]
    pullback = tail.iloc[peak_i + 1 : trough_i + 1]
    rebound = tail.iloc[trough_i + 1 :]
    rally_avg = rally["volume"].mean()
    shrink = pullback["volume"].mean() / rally_avg if rally_avg > 0 else math.inf
    near_vwap = abs(trough["close"] / trough["vwap"] - 1) <= 0.005
    near_breakout = abs(trough["close"] / prior_high - 1) <= 0.005
    support = trough["close"] >= min(trough["vwap"], prior_high) * 0.998 and (
        near_vwap or near_breakout
    )
    rebound_ok = (
        not rebound.empty
        and rebound["close"].max() >= trough["close"] * 1.002
        and rebound.iloc[-1]["close"] >= rebound.iloc[-1]["vwap"]
    )
    if not (shrink <= 0.70 and support and rebound_ok):
        reasons = []
        if shrink > 0.70:
            reasons.append("回踩未缩量")
        if not support:
            reasons.append("支撑未确认")
        if not rebound_ok:
            reasons.append("重新承接不足")
        return TailResult(False, "；".join(reasons), shrink_ratio=shrink)
    confirm_row = rebound.iloc[-1]
    later = group[group["timestamp"] > confirm_row["timestamp"]]
    if later.empty:
        return TailResult(False, "确认后无可成交K线", shrink_ratio=shrink)
    entry = later.iloc[0]
    return TailResult(
        True,
        "通过",
        confirm_time=confirm_row["timestamp"],
        entry_time=entry["timestamp"],
        entry_price=float(entry["bar_vwap"]),
        shrink_ratio=float(shrink),
    )


def tail_1m(group: pd.DataFrame) -> TailResult:
    group = prepare_group(group)
    before = group[group["tm"].between("13:30", "14:29")]
    tail = group[group["tm"].between("14:30", "14:50")].reset_index(drop=True)
    if before.empty or len(tail) < 12:
        return TailResult(False, "1分钟数据不足")
    prior_high = before["close"].max()
    peak_i = int(tail["close"].idxmax())
    if peak_i < 1 or peak_i > len(tail) - 4 or tail.loc[peak_i, "close"] <= prior_high:
        return TailResult(False, "未形成可回踩突破")
    after_peak = tail.iloc[peak_i + 1 :]
    trough_i = int(after_peak["close"].idxmin())
    if trough_i > len(tail) - 3:
        return TailResult(False, "回踩过晚")
    trough = tail.loc[trough_i]
    rally = tail.iloc[: peak_i + 1]
    pullback = tail.iloc[peak_i + 1 : trough_i + 1]
    rebound = tail.iloc[trough_i + 1 :]
    rally_avg = rally["volume"].mean()
    shrink = pullback["volume"].mean() / rally_avg if rally_avg > 0 else math.inf
    near_vwap = abs(trough["close"] / trough["vwap"] - 1) <= 0.005
    near_breakout = abs(trough["close"] / prior_high - 1) <= 0.005
    support = trough["close"] >= min(trough["vwap"], prior_high) * 0.998 and (
        near_vwap or near_breakout
    )
    below_run = max_consecutive_below(tail.iloc[peak_i + 1 : trough_i + 2])
    confirm = None
    previous_close = trough["close"]
    for _, row in rebound.iterrows():
        if row["close"] >= trough["close"] * 1.002 and row["close"] >= row["vwap"] and row["close"] > previous_close:
            confirm = row
            break
        previous_close = row["close"]
    if not (shrink <= 0.70 and support and below_run <= 3 and confirm is not None):
        reasons = []
        if shrink > 0.70:
            reasons.append("回踩未缩量")
        if not support:
            reasons.append("支撑未确认")
        if below_run > 3:
            reasons.append("均价线下超过3分钟")
        if confirm is None:
            reasons.append("重新承接不足")
        return TailResult(False, "；".join(reasons), shrink_ratio=shrink)
    later = group[group["timestamp"] > confirm["timestamp"]]
    if later.empty:
        return TailResult(False, "确认后无可成交分钟", shrink_ratio=shrink)
    entry = later.iloc[0]
    return TailResult(
        True,
        "通过",
        confirm_time=confirm["timestamp"],
        entry_time=entry["timestamp"],
        entry_price=float(entry["bar_vwap"]),
        shrink_ratio=float(shrink),
    )


def exits_for_signal(all_bars: pd.DataFrame, date: str, entry_price: float, resolution: str):
    dates = sorted(all_bars["date"].unique())
    later_dates = [item for item in dates if item > date]
    if not later_dates or not math.isfinite(entry_price) or entry_price <= 0:
        return {}
    next_date = later_dates[0]
    next_day = all_bars[all_bars["date"] == next_date].copy()
    if next_day.empty:
        return {}
    next_day = prepare_group(next_day.drop(columns=["date", "tm", "cum_volume", "cum_amount", "vwap", "bar_vwap"], errors="ignore"))
    if resolution == "1m":
        first = next_day[next_day["tm"] == "09:31"]
        to935 = next_day[next_day["tm"].between("09:31", "09:35")]
    else:
        first = next_day[next_day["tm"] == "09:35"]
        to935 = first
    to1000 = next_day[next_day["tm"].between("09:31", "10:00")]
    def group_vwap(frame):
        return frame["amount"].sum() / frame["volume"].sum() if not frame.empty and frame["volume"].sum() > 0 else math.nan
    prices = {
        "next_date": next_date,
        "exit_first": group_vwap(first),
        "exit_0935": group_vwap(to935),
        "exit_1000": group_vwap(to1000),
    }
    for key in ("exit_first", "exit_0935", "exit_1000"):
        prices["ret_" + key[5:]] = (prices[key] / entry_price - 1) * 100 if math.isfinite(prices[key]) else math.nan
    return prices


def evaluate_layer(connection, bars_path, feature_frame, resolution):
    base = feature_frame[feature_frame["base_candidate"]].copy()
    candidate_bars = load_candidate_bars(connection, bars_path, base)
    rows = []
    if not candidate_bars.empty:
        candidate_bars["date"] = candidate_bars["timestamp"].str[:10]
        for (code, date), group in candidate_bars.groupby(["code", "date"]):
            result = tail_1m(group) if resolution == "1m" else tail_5m(group)
            meta = base[(base["code"] == code) & (base["date"] == date)].iloc[0]
            row = {
                "code": code,
                "date": date,
                "name": meta.get("current_name", ""),
                "industry": meta.get("industry", "未知"),
                "ret1430": meta.get("ret1430"),
                "turnover1430": meta.get("turnover1430"),
                "amount_percentile": meta.get("amount_percentile"),
                "volume_ratio1430": meta.get("volume_ratio1430"),
                "above_vwap_ratio": meta.get("above_vwap_ratio"),
                "tail_ok": result.ok,
                "tail_reason": result.reason,
                "confirm_time": result.confirm_time,
                "entry_time": result.entry_time,
                "entry_price": result.entry_price,
                "shrink_ratio": result.shrink_ratio,
            }
            all_code_bars = connection.execute(
                "SELECT * FROM read_parquet(?) WHERE code = ? AND substr(timestamp,1,10) >= ? ORDER BY timestamp",
                [str(bars_path), code, date],
            ).df()
            all_code_bars["date"] = all_code_bars["timestamp"].str[:10]
            signal_day = prepare_group(all_code_bars[all_code_bars["date"] == date])
            base_entry_rows = signal_day[signal_day["tm"] > "14:30"]
            if not base_entry_rows.empty:
                base_entry = base_entry_rows.iloc[0]
                row["base_entry_time"] = base_entry["timestamp"]
                row["base_entry_price"] = float(base_entry["bar_vwap"])
                base_exits = exits_for_signal(
                    all_code_bars, date, row["base_entry_price"], resolution
                )
                row.update({"base_" + key: value for key, value in base_exits.items()})
            if result.ok and result.entry_price:
                row.update(exits_for_signal(all_code_bars, date, result.entry_price, resolution))
            rows.append(row)
    return base, pd.DataFrame(rows)


def funnel(frame: pd.DataFrame):
    order = [
        ("data_valid", "数据有效"),
        ("check_hot_sector", "热门板块"),
        ("check_relative_strength", "板块内相对强势"),
        ("check_turnover", "换手率5%—10%"),
        ("check_amount", "成交额前25%"),
        ("check_above_vwap", "VWAP强度"),
        ("check_volume_ratio", "量比>1"),
        ("check_recent_strong", "近20日强势"),
        ("check_volume3", "连续3日站上120日均量"),
    ]
    active = pd.Series(True, index=frame.index)
    output = []
    for column, label in order:
        active &= frame[column].fillna(False)
        output.append({"step": label, "count": int(active.sum())})
    return output


def signal_metrics(signals: pd.DataFrame):
    if signals.empty:
        return {"signal_count": 0}
    passed = signals[signals["tail_ok"]]
    result = {"observed_count": len(signals), "signal_count": int(len(passed))}
    for name in ("first", "0935", "1000"):
        column = "ret_" + name
        values = passed[column].dropna() if column in passed else pd.Series(dtype=float)
        result[name] = {
            "trade_count": int(len(values)),
            "gross_mean_pct": None if values.empty else round(float(values.mean()), 4),
            "gross_median_pct": None if values.empty else round(float(values.median()), 4),
            "win_rate": None if values.empty else round(float((values > 0).mean()), 4),
            "after_10bp_slippage_mean_pct": None if values.empty else round(float(values.mean() - 0.10), 4),
        }
    return result


def base_candidate_metrics(candidates: pd.DataFrame):
    if candidates.empty:
        return {"candidate_count": 0}
    result = {"candidate_count": int(len(candidates))}
    for name in ("first", "0935", "1000"):
        column = "base_ret_" + name
        values = candidates[column].dropna() if column in candidates else pd.Series(dtype=float)
        result[name] = {
            "trade_count": int(len(values)),
            "gross_mean_pct": None if values.empty else round(float(values.mean()), 4),
            "gross_median_pct": None if values.empty else round(float(values.median()), 4),
            "win_rate": None if values.empty else round(float((values > 0).mean()), 4),
            "after_10bp_slippage_mean_pct": None if values.empty else round(float(values.mean() - 0.10), 4),
        }
    return result


def select_matched_controls(features: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    selected = []
    used = set()
    match_columns = ["ret1430", "turnover1430", "amount_percentile", "above_vwap_ratio"]
    for _, target in base.sort_values(["date", "code"]).iterrows():
        pool = features[
            features["data_valid"]
            & ~features["base_candidate"]
            & features["date"].eq(target["date"])
            & features["industry"].eq(target["industry"])
            & features["code"].ne(target["code"])
        ].copy()
        if pool.empty:
            continue
        pool = pool[~pool.apply(lambda row: (row["date"], row["code"]) in used, axis=1)]
        if pool.empty:
            continue
        score = pd.Series(0.0, index=pool.index)
        for column in match_columns:
            scale = float(pool[column].std())
            if not math.isfinite(scale) or scale <= 1e-9:
                scale = 1.0
            score += ((pool[column] - target[column]) / scale) ** 2
        log_scale = np.log(pool["float_shares_approx"].clip(lower=1.0)).std()
        if not math.isfinite(log_scale) or log_scale <= 1e-9:
            log_scale = 1.0
        score += (
            (
                np.log(pool["float_shares_approx"].clip(lower=1.0))
                - math.log(max(float(target["float_shares_approx"]), 1.0))
            )
            / log_scale
        ) ** 2
        chosen = pool.loc[score.idxmin()].copy()
        used.add((chosen["date"], chosen["code"]))
        chosen["matched_for_date"] = target["date"]
        chosen["matched_for_code"] = target["code"]
        selected.append(chosen)
    return pd.DataFrame(selected)


def add_hypothetical_returns(connection, bars_path, frame, resolution):
    rows = []
    for _, meta in frame.iterrows():
        date, code = meta["date"], meta["code"]
        all_code_bars = connection.execute(
            "SELECT * FROM read_parquet(?) WHERE code = ? AND substr(timestamp,1,10) >= ? ORDER BY timestamp",
            [str(bars_path), code, date],
        ).df()
        if all_code_bars.empty:
            continue
        all_code_bars["date"] = all_code_bars["timestamp"].str[:10]
        signal_day = prepare_group(all_code_bars[all_code_bars["date"] == date])
        entries = signal_day[signal_day["tm"] > "14:30"]
        if entries.empty:
            continue
        entry = entries.iloc[0]
        row = meta.to_dict()
        row["base_entry_time"] = entry["timestamp"]
        row["base_entry_price"] = float(entry["bar_vwap"])
        outcomes = exits_for_signal(all_code_bars, date, row["base_entry_price"], resolution)
        row.update({"base_" + key: value for key, value in outcomes.items()})
        rows.append(row)
    return pd.DataFrame(rows)


def matched_comparison(base_outcomes: pd.DataFrame, control_outcomes: pd.DataFrame):
    if base_outcomes.empty or control_outcomes.empty:
        return {"pair_count": 0}
    merged = base_outcomes.merge(
        control_outcomes,
        left_on=["date", "code"],
        right_on=["matched_for_date", "matched_for_code"],
        suffixes=("_signal", "_control"),
    )
    result = {"pair_count": int(len(merged))}
    rng = np.random.default_rng(20260820)
    for name in ("first", "0935", "1000"):
        signal_column = f"base_ret_{name}_signal"
        control_column = f"base_ret_{name}_control"
        valid = merged[["date_signal", signal_column, control_column]].dropna()
        valid["difference"] = valid[signal_column] - valid[control_column]
        daily = valid.groupby("date_signal")["difference"].mean().to_numpy()
        if len(daily):
            bootstrap = daily[rng.integers(0, len(daily), (20000, len(daily)))].mean(axis=1)
            ci = [round(float(np.quantile(bootstrap, 0.025)), 4), round(float(np.quantile(bootstrap, 0.975)), 4)]
        else:
            ci = [None, None]
        result[name] = {
            "pairs": int(len(valid)),
            "signal_mean_pct": None if valid.empty else round(float(valid[signal_column].mean()), 4),
            "control_mean_pct": None if valid.empty else round(float(valid[control_column].mean()), 4),
            "mean_difference_pct": None if valid.empty else round(float(valid["difference"].mean()), 4),
            "daily_block_bootstrap_ci95": ci,
        }
    return result


def main() -> None:
    args = parse_args()
    input_dir = pathlib.Path(args.input).expanduser().resolve()
    output_dir = pathlib.Path(args.output).expanduser().resolve()
    if output_dir.exists():
        raise SystemExit(f"Output already exists; refusing to overwrite: {output_dir}")
    output_dir.mkdir(parents=True)

    connection = duckdb.connect()
    spot = load_spot(input_dir / "spot_metadata.json")
    industry = pq.read_table(input_dir / "industry.parquet").to_pandas()
    universe = pq.read_table(input_dir / "universe.parquet").to_pandas()
    industry_snapshots = latest_snapshot_maps(industry, "industry")
    st_snapshots = latest_snapshot_maps(universe, "is_st_name")
    daily = daily_features(connection, input_dir / "daily.parquet")

    five = intraday_features(
        connection, input_dir / "bars_5m.parquet", daily, spot, args.start, args.end
    )
    five, five_sector = add_sector_and_checks(five, industry_snapshots, st_snapshots)
    five_base, five_tail = evaluate_layer(
        connection, input_dir / "bars_5m.parquet", five, "5m"
    )
    five_controls = select_matched_controls(five, five_base)
    five_controls = add_hypothetical_returns(
        connection, input_dir / "bars_5m.parquet", five_controls, "5m"
    )

    one = intraday_features(
        connection,
        input_dir / "bars_1m.parquet",
        daily,
        spot,
        args.one_minute_start,
        args.end,
    )
    one, one_sector = add_sector_and_checks(one, industry_snapshots, st_snapshots)
    one_base, one_tail = evaluate_layer(
        connection, input_dir / "bars_1m.parquet", one, "1m"
    )
    one_controls = select_matched_controls(one, one_base)
    one_controls = add_hypothetical_returns(
        connection, input_dir / "bars_1m.parquet", one_controls, "1m"
    )

    for name, frame in (
        ("features_5m.parquet", five),
        ("sector_stats_5m.parquet", five_sector),
        ("tail_checks_5m.parquet", five_tail),
        ("matched_controls_5m.parquet", five_controls),
        ("features_1m.parquet", one),
        ("sector_stats_1m.parquet", one_sector),
        ("tail_checks_1m.parquet", one_tail),
        ("matched_controls_1m.parquet", one_controls),
    ):
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), output_dir / name, compression="zstd")

    overlap_dates = sorted(set(one["date"]).intersection(five["date"]))
    five_signals = set(
        zip(
            five_tail.loc[five_tail.get("tail_ok", False) == True, "date"] if not five_tail.empty else [],
            five_tail.loc[five_tail.get("tail_ok", False) == True, "code"] if not five_tail.empty else [],
        )
    )
    one_signals = set(
        zip(
            one_tail.loc[one_tail.get("tail_ok", False) == True, "date"] if not one_tail.empty else [],
            one_tail.loc[one_tail.get("tail_ok", False) == True, "code"] if not one_tail.empty else [],
        )
    )
    report = {
        "experiment": "YYX-OH-FREE-PRESTUDY-V1",
        "status": "PRELIMINARY_NOT_FORMAL_BACKTEST",
        "period_5m": [args.start, args.end],
        "period_1m": [args.one_minute_start, args.end],
        "limitations": [
            "5分钟层不能验证2—3分钟收回及分钟内先后顺序",
            "流通股本使用2026-08-20新浪快照近似，可能影响换手率边界样本",
            "行业使用2026-07-01、2026-08-03、2026-08-20快照，不是逐日快照",
            "近20日强势沿用当前脚本的单日涨幅>=5%临时定义",
            "收益仅展示毛收益及双边合计10bp滑点情景，未计佣金和法定税费",
        ],
        "five_minute": {
            "dates": int(five["date"].nunique()),
            "feature_rows": int(len(five)),
            "valid_rows": int(five["data_valid"].sum()),
            "hot_sector_day_count": int(five_sector.loc[five_sector["hot_sector"], "date"].nunique()) if not five_sector.empty else 0,
            "hot_sector_count": int(five_sector["hot_sector"].sum()) if not five_sector.empty else 0,
            "funnel": funnel(five),
            "base_candidate_count": int(len(five_base)),
            "base_candidate_days": int(five_base["date"].nunique()) if not five_base.empty else 0,
            "base_candidate_metrics": base_candidate_metrics(five_tail),
            "matched_comparison": matched_comparison(five_tail, five_controls),
            "metrics": signal_metrics(five_tail),
        },
        "one_minute": {
            "dates": int(one["date"].nunique()),
            "feature_rows": int(len(one)),
            "valid_rows": int(one["data_valid"].sum()),
            "hot_sector_day_count": int(one_sector.loc[one_sector["hot_sector"], "date"].nunique()) if not one_sector.empty else 0,
            "hot_sector_count": int(one_sector["hot_sector"].sum()) if not one_sector.empty else 0,
            "funnel": funnel(one),
            "base_candidate_count": int(len(one_base)),
            "base_candidate_days": int(one_base["date"].nunique()) if not one_base.empty else 0,
            "base_candidate_metrics": base_candidate_metrics(one_tail),
            "matched_comparison": matched_comparison(one_tail, one_controls),
            "metrics": signal_metrics(one_tail),
        },
        "cross_resolution": {
            "overlap_dates": overlap_dates,
            "five_signal_count_on_overlap": sum(date in overlap_dates for date, _ in five_signals),
            "one_signal_count": len(one_signals),
            "same_signal_count": len(five_signals.intersection(one_signals)),
        },
    }
    (output_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("RESULT=" + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
