#!/usr/bin/env python3
"""运行免费预研消融 V1 的四个预注册单因素模型。"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from collections import Counter

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from analyze_free_prestudy import (
    TailResult,
    exits_for_signal,
    load_candidate_bars,
    matched_comparison,
    max_consecutive_below,
    prepare_group,
    select_matched_controls,
    signal_metrics,
    tail_1m,
    tail_5m,
)


CHECK_COLUMNS = [
    "check_hot_sector",
    "check_relative_strength",
    "check_turnover",
    "check_amount",
    "check_above_vwap",
    "check_volume_ratio",
    "check_recent_strong",
    "check_volume3",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="原始行情目录")
    parser.add_argument("--features", required=True, help="免费预研 v3 分析目录")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def alt_pre1430_tail(group: pd.DataFrame, resolution: str) -> TailResult:
    group = prepare_group(group)
    if resolution == "1m":
        reference = group[group["tm"].between("13:30", "14:14")]
        rally_window = group[group["tm"].between("14:15", "14:29")].reset_index(drop=True)
        tail = group[group["tm"].between("14:30", "14:50")].reset_index(drop=True)
        min_tail = 12
    else:
        reference = group[group["tm"].between("13:30", "14:10")]
        rally_window = group[group["tm"].isin(["14:15", "14:20", "14:25"])].reset_index(drop=True)
        tail = group[group["tm"].between("14:30", "14:50")].reset_index(drop=True)
        min_tail = 5
    if reference.empty or rally_window.empty or len(tail) < min_tail:
        return TailResult(False, "数据不足")
    reference_high = float(reference["close"].max())
    peak_i = int(rally_window["close"].idxmax())
    peak = rally_window.loc[peak_i]
    if peak["close"] <= reference_high:
        return TailResult(False, "14:30前未突破参考平台")
    rally = rally_window.iloc[: peak_i + 1]
    trough_i = int(tail["close"].idxmin())
    if trough_i > len(tail) - 2:
        return TailResult(False, "回踩过晚")
    trough = tail.loc[trough_i]
    pullback = tail.iloc[: trough_i + 1]
    rebound = tail.iloc[trough_i + 1 :]
    rally_avg = float(rally["volume"].mean())
    shrink = float(pullback["volume"].mean() / rally_avg) if rally_avg > 0 else math.inf
    near_vwap = abs(trough["close"] / trough["vwap"] - 1) <= 0.005
    near_breakout = abs(trough["close"] / reference_high - 1) <= 0.005
    support = trough["close"] >= min(trough["vwap"], reference_high) * 0.998 and (
        near_vwap or near_breakout
    )
    below_run = max_consecutive_below(tail.iloc[: trough_i + 2])
    confirm = None
    previous_close = float(trough["close"])
    for _, row in rebound.iterrows():
        if (
            row["close"] >= trough["close"] * 1.002
            and row["close"] >= row["vwap"]
            and row["close"] > previous_close
        ):
            confirm = row
            break
        previous_close = float(row["close"])
    below_ok = True if resolution == "5m" else below_run <= 3
    if not (shrink <= 0.70 and support and below_ok and confirm is not None):
        reasons = []
        if shrink > 0.70:
            reasons.append("回踩未缩量")
        if not support:
            reasons.append("支撑未确认")
        if not below_ok:
            reasons.append("均价线下超过3分钟")
        if confirm is None:
            reasons.append("重新承接不足")
        return TailResult(False, "；".join(reasons), shrink_ratio=shrink)
    later = group[group["timestamp"] > confirm["timestamp"]]
    if later.empty:
        return TailResult(False, "确认后无可成交K线", shrink_ratio=shrink)
    entry = later.iloc[0]
    return TailResult(
        True,
        "通过",
        confirm_time=str(confirm["timestamp"]),
        entry_time=str(entry["timestamp"]),
        entry_price=float(entry["bar_vwap"]),
        shrink_ratio=shrink,
    )


def model_mask(features: pd.DataFrame, model: str) -> pd.Series:
    excluded = {
        "M0": set(),
        "M1_NO_HOT_SECTOR": {"check_hot_sector"},
        "M2_NO_VOLUME3": {"check_volume3"},
        "M3_NO_TURNOVER": {"check_turnover"},
        "M4_PRE1430_BREAKOUT": set(),
    }[model]
    columns = [column for column in CHECK_COLUMNS if column not in excluded]
    return features[columns].fillna(False).all(axis=1)


def evaluate_model(connection, bars_path, features, model, resolution):
    features = features.copy()
    features["base_candidate"] = model_mask(features, model)
    candidates = features[features["base_candidate"]].copy()
    bars = load_candidate_bars(connection, bars_path, candidates)
    output = []
    if bars.empty:
        return features, candidates, pd.DataFrame()
    bars["date"] = bars["timestamp"].str[:10]
    for (code, date), group in bars.groupby(["code", "date"]):
        if model == "M4_PRE1430_BREAKOUT":
            tail = alt_pre1430_tail(group, resolution)
        else:
            tail = tail_1m(group) if resolution == "1m" else tail_5m(group)
        meta = candidates[(candidates["code"] == code) & (candidates["date"] == date)].iloc[0]
        row = {
            "model": model,
            "resolution": resolution,
            "date": date,
            "code": code,
            "name": meta.get("current_name", ""),
            "industry": meta.get("industry", "未知"),
            "ret1430": meta.get("ret1430"),
            "turnover1430": meta.get("turnover1430"),
            "amount_percentile": meta.get("amount_percentile"),
            "volume_ratio1430": meta.get("volume_ratio1430"),
            "above_vwap_ratio": meta.get("above_vwap_ratio"),
            "tail_ok": tail.ok,
            "tail_reason": tail.reason,
            "confirm_time": tail.confirm_time,
            "entry_time": tail.entry_time,
            "entry_price": tail.entry_price,
            "shrink_ratio": tail.shrink_ratio,
        }
        if tail.ok and tail.entry_price:
            all_bars = connection.execute(
                "SELECT * FROM read_parquet(?) WHERE code=? AND substr(timestamp,1,10)>=? ORDER BY timestamp",
                [str(bars_path), code, date],
            ).df()
            all_bars["date"] = all_bars["timestamp"].str[:10]
            outcomes = exits_for_signal(all_bars, date, tail.entry_price, resolution)
            row.update(outcomes)
            for key in ("first", "0935", "1000"):
                row[f"base_ret_{key}"] = row.get(f"ret_{key}")
        output.append(row)
    return features, candidates, pd.DataFrame(output)


def matched_controls_at_signal_time(connection, bars_path, features, signals, resolution):
    if signals.empty:
        return pd.DataFrame()
    signal_features = features.merge(
        signals.loc[signals["tail_ok"], ["date", "code", "entry_time"]],
        on=["date", "code"],
        how="inner",
    )
    controls = select_matched_controls(features, signal_features)
    rows = []
    for _, control in controls.iterrows():
        signal = signals[
            signals["date"].eq(control["matched_for_date"])
            & signals["code"].eq(control["matched_for_code"])
        ].iloc[0]
        date, code, entry_time = control["date"], control["code"], signal["entry_time"]
        all_bars = connection.execute(
            "SELECT * FROM read_parquet(?) WHERE code=? AND substr(timestamp,1,10)>=? ORDER BY timestamp",
            [str(bars_path), code, date],
        ).df()
        if all_bars.empty:
            continue
        all_bars["date"] = all_bars["timestamp"].str[:10]
        day = prepare_group(all_bars[all_bars["date"] == date])
        entry = day[day["timestamp"] == entry_time]
        if entry.empty:
            continue
        row = control.to_dict()
        row["base_entry_time"] = entry_time
        row["base_entry_price"] = float(entry.iloc[0]["bar_vwap"])
        outcomes = exits_for_signal(all_bars, date, row["base_entry_price"], resolution)
        row.update({"base_" + key: value for key, value in outcomes.items()})
        for key in ("first", "0935", "1000"):
            row.setdefault(f"base_ret_{key}", None)
        rows.append(row)
    return pd.DataFrame(rows)


def daily_signal_ci(signals: pd.DataFrame):
    passed = signals[signals["tail_ok"]] if not signals.empty else pd.DataFrame()
    result = {}
    rng = np.random.default_rng(20260820)
    for name in ("first", "0935", "1000"):
        column = f"ret_{name}"
        if passed.empty or column not in passed:
            result[name] = {"days": 0, "mean_pct": None, "ci95": [None, None]}
            continue
        daily = passed.dropna(subset=[column]).groupby("date")[column].mean().to_numpy()
        if not len(daily):
            result[name] = {"days": 0, "mean_pct": None, "ci95": [None, None]}
            continue
        bootstrap = daily[rng.integers(0, len(daily), (20000, len(daily)))].mean(axis=1)
        result[name] = {
            "days": int(len(daily)),
            "mean_pct": round(float(daily.mean()), 4),
            "ci95": [
                round(float(np.quantile(bootstrap, 0.025)), 4),
                round(float(np.quantile(bootstrap, 0.975)), 4),
            ],
        }
    return result


def summarize(model, candidates, signals, controls):
    reasons = Counter(signals["tail_reason"].tolist()) if not signals.empty else Counter()
    return {
        "model": model,
        "candidate_count": int(len(candidates)),
        "candidate_days": int(candidates["date"].nunique()) if not candidates.empty else 0,
        "tail_reasons": dict(reasons.most_common()),
        "signal_metrics": signal_metrics(signals),
        "daily_signal_metrics": daily_signal_ci(signals),
        "matched_comparison": matched_comparison(signals, controls),
    }


def main() -> None:
    args = parse_args()
    input_dir = pathlib.Path(args.input).expanduser().resolve()
    feature_dir = pathlib.Path(args.features).expanduser().resolve()
    output_dir = pathlib.Path(args.output).expanduser().resolve()
    if output_dir.exists():
        raise SystemExit(f"Output already exists; refusing to overwrite: {output_dir}")
    output_dir.mkdir(parents=True)

    connection = duckdb.connect()
    models = ["M0", "M1_NO_HOT_SECTOR", "M2_NO_VOLUME3", "M3_NO_TURNOVER", "M4_PRE1430_BREAKOUT"]
    report = {
        "experiment": "YYX-OH-FREE-ABLATION-V1",
        "status": "PRELIMINARY_NOT_FORMAL_BACKTEST",
        "models": {},
    }
    all_signals = []
    all_controls = []
    for resolution in ("5m", "1m"):
        features = pq.read_table(feature_dir / f"features_{resolution}.parquet").to_pandas()
        bars_path = input_dir / f"bars_{resolution}.parquet"
        report["models"][resolution] = {}
        for model in models:
            model_features, candidates, signals = evaluate_model(
                connection, bars_path, features, model, resolution
            )
            controls = matched_controls_at_signal_time(
                connection, bars_path, model_features, signals, resolution
            )
            report["models"][resolution][model] = summarize(
                model, candidates, signals, controls
            )
            if not signals.empty:
                all_signals.append(signals)
            if not controls.empty:
                controls["model"] = model
                controls["resolution"] = resolution
                all_controls.append(controls)
            print(
                f"{resolution} {model} candidates={len(candidates)} "
                f"signals={int(signals['tail_ok'].sum()) if not signals.empty else 0}",
                flush=True,
            )

    signals_frame = pd.concat(all_signals, ignore_index=True) if all_signals else pd.DataFrame()
    controls_frame = pd.concat(all_controls, ignore_index=True) if all_controls else pd.DataFrame()
    if not signals_frame.empty:
        pq.write_table(
            pa.Table.from_pandas(signals_frame, preserve_index=False),
            output_dir / "all_tail_checks.parquet",
            compression="zstd",
        )
    if not controls_frame.empty:
        pq.write_table(
            pa.Table.from_pandas(controls_frame, preserve_index=False),
            output_dir / "matched_controls.parquet",
            compression="zstd",
        )
    (output_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("RESULT=" + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
