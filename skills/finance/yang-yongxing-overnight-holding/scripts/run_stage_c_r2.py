#!/usr/bin/env python3
"""运行 YYX-OH-V1C-R2 的 2026 数据门禁与开发期参数分析。"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import pathlib
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy import stats


EXPERIMENT_ID = "YYX-OH-V1C-R2"
SEED = 20260824
CAPITAL = 1_000_000.0
MAX_HOLD = 3
SIGNAL_START = "2026-06-01"
SIGNAL_END = "2026-08-21"
RAW_CUTOFF = "2026-08-24"
CONDITIONS = (
    "sector_strength",
    "sector_up_breadth",
    "sector_vwap_breadth",
    "sector_strong_count",
    "sector_activity",
    "individual_strength",
    "volume_ratio",
    "turnover",
    "amount_rank",
    "recent_strong",
    "continuous_volume",
    "vwap_ratio",
)
BASE_CONFIG: dict[str, Any] = {
    "sector_top": 0.25,
    "sector_up_ratio": 0.55,
    "sector_vwap_ratio": 0.55,
    "sector_strong_count": 2,
    "sector_activity": 1.0,
    "individual_top": 0.25,
    "volume_ratio": 1.0,
    "turnover_band": (5.0, 10.0),
    "amount_top": 0.25,
    "recent_window": 20,
    "recent_pct": 5.0,
    "volume_ma": 120,
    "volume_days": 3,
    "vwap_ratio": 0.70,
}
PARAMETERS: dict[str, list[Any]] = {
    "sector_top": [0.10, 0.20, 0.25, 0.30, 0.40],
    "sector_up_ratio": [0.50, 0.55, 0.60, 0.65, 0.70],
    "sector_vwap_ratio": [0.50, 0.55, 0.60, 0.65, 0.70],
    "sector_strong_count": [1, 2, 3],
    "sector_activity": [0.8, 1.0, 1.2, 1.5],
    "individual_top": [0.10, 0.20, 0.25, 0.30, 0.40],
    "volume_ratio": [0.8, 1.0, 1.2, 1.5],
    "turnover_band": [(3.0, 8.0), (5.0, 10.0), (5.0, 15.0), (3.0, 12.0)],
    "amount_top": [0.10, 0.20, 0.25, 0.30, 0.40],
    "recent_window": [10, 15, 20, 30],
    "recent_pct": [3.0, 5.0, 7.0],
    "volume_ma": [20, 60, 90, 120],
    "volume_days": [2, 3, 4, 5],
    "vwap_ratio": [0.60, 0.65, 0.70, 0.75, 0.80],
}
PARAM_CONDITION = {
    "sector_top": "sector_strength",
    "sector_up_ratio": "sector_up_breadth",
    "sector_vwap_ratio": "sector_vwap_breadth",
    "sector_strong_count": "sector_strong_count",
    "sector_activity": "sector_activity",
    "individual_top": "individual_strength",
    "volume_ratio": "volume_ratio",
    "turnover_band": "turnover",
    "amount_top": "amount_rank",
    "recent_window": "recent_strong",
    "recent_pct": "recent_strong",
    "volume_ma": "continuous_volume",
    "volume_days": "continuous_volume",
    "vwap_ratio": "vwap_ratio",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="phase", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--input", required=True)
    audit.add_argument("--output", required=True)
    audit.add_argument(
        "--cross-source-daily",
        default=(
            "data/yang-yongxing-overnight-holding/"
            "20260701_20260820-free-prestudy-20260820/daily.parquet"
        ),
    )
    develop = subparsers.add_parser("develop")
    develop.add_argument("--input", required=True)
    develop.add_argument("--output", required=True)
    return parser.parse_args()


def json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(type(value).__name__)


def write_json(path: pathlib.Path, value: dict | list) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=json_value),
        encoding="utf-8",
    )


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sql_path(path: pathlib.Path | str) -> str:
    return str(path).replace("'", "''")


def fingerprint(path: pathlib.Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def scalar(connection: duckdb.DuckDBPyConnection, query: str) -> Any:
    return connection.execute(query).fetchone()[0]


def row_dict(connection: duckdb.DuckDBPyConnection, query: str) -> dict:
    cursor = connection.execute(query)
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, cursor.fetchone()))


def markdown_quality(report: dict) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in report["checks"].items()
    )
    return "\n".join(
        [
            "# 阶段 C R2 2026 开发集数据门禁",
            "",
            f"- 状态：`{report['status']}`",
            f"- 采集代码：{report['collection']['completed_codes']}/{report['collection']['total_codes']}",
            f"- 特征行：{report['metrics']['feature_rows']:,}",
            f"- 合格信号时点行：{report['metrics']['eligible_rows']:,}",
            f"- 日期：{report['metrics']['min_date']} 至 {report['metrics']['max_date']}",
            "",
            "## 检查",
            "",
            checks,
            "",
            "本门禁只证明 5 分钟基础筛选开发数据可用于分析，不代表策略或参数有效。",
        ]
    ) + "\n"


def run_audit(input_dir: pathlib.Path, output: pathlib.Path, cross_source: pathlib.Path) -> None:
    if output.exists():
        raise SystemExit(f"门禁输出目录已存在：{output}")
    state_path = input_dir / "state.json"
    if not state_path.is_file():
        raise SystemExit("采集 state.json 不存在")
    state = read_json(state_path)
    if state.get("status") != "COMPLETE":
        raise SystemExit("采集尚未 COMPLETE，不运行数据门禁")
    parameters = state.get("parameters", {})
    if parameters.get("start") != SIGNAL_START or parameters.get("end") != SIGNAL_END:
        raise SystemExit("采集信号区间与 R2 冻结配置不一致")
    if state.get("exit_end") != RAW_CUTOFF:
        raise SystemExit("采集退出截止与 R2 冻结配置不一致")
    feature_glob = input_dir / "features/*.parquet"
    daily_glob = input_dir / "daily/*.parquet"
    required = [input_dir / name for name in ("universe.parquet", "industry.parquet", "trade_calendar.parquet")]
    if not all(path.is_file() for path in required) or not cross_source.is_file():
        raise SystemExit("门禁输入文件不完整")

    output.mkdir(parents=True)
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.execute(
        f"CREATE VIEW features AS SELECT * FROM read_parquet('{sql_path(feature_glob)}')"
    )
    connection.execute(
        f"CREATE VIEW daily AS SELECT * FROM read_parquet('{sql_path(daily_glob)}')"
    )
    connection.execute(
        f"CREATE VIEW industries AS SELECT * FROM read_parquet('{sql_path(input_dir / 'industry.parquet')}')"
    )
    connection.execute(
        """
        CREATE VIEW with_industry AS
        SELECT f.*,i.industry,i.classification,
          i.snapshot_date AS industry_snapshot_date
        FROM features f ASOF LEFT JOIN industries i
          ON f.code=i.code AND f.date>=i.snapshot_date
        """
    )
    base_predicate = """
      date BETWEEN '2026-06-01' AND '2026-08-21'
      AND trade_status=1 AND NOT is_st
      AND listing_market_days_prior>=60 AND NOT is_resume_day
      AND isfinite(price1430) AND price1430>0
      AND isfinite(cum_volume1430) AND cum_volume1430>0
      AND isfinite(cum_amount1430) AND cum_amount1430>0
      AND isfinite(vwap1430) AND vwap1430>0
      AND isfinite(volume_ratio1430) AND volume_ratio1430>0
      AND isfinite(turnover1430) AND turnover1430>0
      AND recent_30_complete AND previous20_complete
      AND volume_ma120_d5_complete
      AND industry IS NOT NULL AND trim(industry)<>''
    """
    eligible_predicate = base_predicate + """
      AND exact_1430_complete
      AND NOT minute_daily_volume_conflict
      AND isfinite(full_day_volume_relative_error)
      AND full_day_volume_relative_error<=0.02
    """
    metrics = row_dict(
        connection,
        f"""
        SELECT count(*) AS feature_rows,
          count(DISTINCT code||'|'||date) AS distinct_feature_keys,
          min(date) AS min_date,max(date) AS max_date,
          count(DISTINCT date) AS actual_dates,
          count(*) FILTER(WHERE {base_predicate}) AS base_rows,
          count(*) FILTER(WHERE ({base_predicate}) AND exact_1430_complete)
            AS exact_1430_rows,
          count(*) FILTER(WHERE ({base_predicate})
            AND isfinite(full_day_volume_relative_error)
            AND full_day_volume_relative_error<=0.02
            AND NOT minute_daily_volume_conflict) AS volume_consistent_rows,
          count(*) FILTER(WHERE {eligible_predicate}) AS eligible_rows,
          count(*) FILTER(WHERE next_market_date>'{RAW_CUTOFF}') AS cutoff_violations,
          count(*) FILTER(WHERE entry_status NOT IN
            ('EXECUTABLE_5M_BAR_MODEL','LIMIT_UP_LOCKED','ENTRY_WINDOW_MISSING')
            OR entry_status IS NULL) AS unresolved_entry_rows,
          count(*) FILTER(WHERE next_exit_first_5m_status NOT IN
            ('EXECUTABLE_5M_BAR_MODEL','EXIT_DAILY_MISSING','EXIT_SUSPENDED',
             'LIMIT_DOWN_LOCKED','EXIT_WINDOW_MISSING')
            OR next_exit_first_5m_status IS NULL
            OR next_exit_to_1000_status NOT IN
            ('EXECUTABLE_5M_BAR_MODEL','EXIT_DAILY_MISSING','EXIT_SUSPENDED',
             'LIMIT_DOWN_LOCKED','EXIT_WINDOW_MISSING')
            OR next_exit_to_1000_status IS NULL) AS unresolved_exit_rows
        FROM with_industry
        """,
    )
    expected_dates = scalar(
        connection,
        f"""
        SELECT count(*) FROM read_parquet('{sql_path(input_dir / 'trade_calendar.parquet')}')
        WHERE date BETWEEN '{SIGNAL_START}' AND '{SIGNAL_END}'
        """,
    )
    coverage = row_dict(
        connection,
        """
        WITH expected AS (
          SELECT date,count(*) AS expected_rows FROM daily
          WHERE date BETWEEN '2026-06-01' AND '2026-08-21'
            AND trade_status=1 AND NOT is_st AND listing_market_days_prior>=60
          GROUP BY date
        ), actual AS (
          SELECT date,count(*) AS actual_rows FROM with_industry
          WHERE date BETWEEN '2026-06-01' AND '2026-08-21'
            AND trade_status=1 AND NOT is_st AND listing_market_days_prior>=60
          GROUP BY date
        )
        SELECT min(actual_rows::DOUBLE/nullif(expected_rows,0)) AS min_daily_coverage,
          avg(actual_rows::DOUBLE/nullif(expected_rows,0)) AS mean_daily_coverage
        FROM expected JOIN actual USING(date)
        """,
    )
    cross_rows = connection.execute(
        f"""
        WITH candidates AS (
          SELECT d.code,d.date,d.open,d.high,d.low,d.close,d.volume,
            s.open AS cross_open,s.high AS cross_high,s.low AS cross_low,
            s.close AS cross_close,s.volume AS cross_volume,
            greatest(abs(d.open-s.open),abs(d.high-s.high),
              abs(d.low-s.low),abs(d.close-s.close)) AS max_price_error,
            abs(d.volume-s.volume)/greatest(d.volume,1.0) AS volume_relative_error
          FROM daily d
          JOIN read_parquet('{sql_path(cross_source)}') s
            ON split_part(d.code,'.',2)=s.code AND d.date=s.date
          WHERE d.date BETWEEN '2026-07-01' AND '2026-08-19'
            AND d.trade_status=1 AND d.volume>0
          ORDER BY hash(d.code||'|'||d.date)
          LIMIT 30
        )
        SELECT *,max_price_error<=0.011 AND volume_relative_error<=0.02 AS pass
        FROM candidates ORDER BY date,code
        """
    ).fetchdf()
    cross_pass = len(cross_rows) == 30 and bool(cross_rows["pass"].all())
    exact_rate = metrics["exact_1430_rows"] / max(metrics["base_rows"], 1)
    volume_rate = metrics["volume_consistent_rows"] / max(metrics["base_rows"], 1)
    checks = {
        "collection_complete": state.get("status") == "COMPLETE",
        "all_codes_complete": len(set(state.get("completed_codes", []))) == len(read_json(input_dir / "codes.json")),
        "no_duplicate_feature_keys": metrics["feature_rows"] == metrics["distinct_feature_keys"],
        "all_signal_dates_present": metrics["actual_dates"] == expected_dates,
        "daily_cross_section_coverage": coverage["min_daily_coverage"] >= 0.98,
        "exact_1430_rate": exact_rate >= 0.995,
        "volume_consistency_rate": volume_rate >= 0.995,
        "entry_fully_classified": metrics["unresolved_entry_rows"] == 0,
        "exit_fully_classified": metrics["unresolved_exit_rows"] == 0,
        "raw_cutoff_respected": metrics["cutoff_violations"] == 0,
        "cross_source_sample": cross_pass,
        "eligible_rows_nonzero": metrics["eligible_rows"] > 0,
    }
    status = "PASS_2026_DEVELOPMENT_DATA" if all(checks.values()) else "BLOCKED_DATA"
    eligible_path = output / "eligible_features.parquet"
    outcomes_path = output / "outcomes.parquet"
    if status == "PASS_2026_DEVELOPMENT_DATA":
        connection.execute(
            f"""
            COPY (
              SELECT '{EXPERIMENT_ID}' AS source_id,
                * EXCLUDE (
                  volume,full_day_5m_volume,full_day_5m_amount,
                  full_day_volume_relative_error,minute_daily_volume_conflict,
                  entry_next_5m_vwap,entry_next_5m_volume,entry_next_5m_amount,
                  entry_next_5m_high,entry_next_5m_low,
                  exit_first_5m_vwap,exit_first_5m_volume,
                  exit_first_5m_high,exit_first_5m_low,
                  exit_to_1000_vwap,exit_to_1000_volume,
                  exit_to_1000_high,exit_to_1000_low,
                  entry_upper_limit,entry_status,entry_executable,
                  next_market_date,next_exit_first_5m_vwap,
                  next_exit_to_1000_vwap,next_exit_first_5m_status,
                  next_exit_to_1000_status,next_exit_first_5m_executable,
                  next_exit_to_1000_executable
                )
              FROM with_industry WHERE {eligible_predicate}
              ORDER BY date,code
            ) TO '{sql_path(eligible_path)}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
        connection.execute(
            f"""
            COPY (
              SELECT '{EXPERIMENT_ID}' AS source_id,code,date,
                entry_next_5m_vwap,entry_next_5m_volume,entry_next_5m_amount,
                entry_next_5m_high,entry_next_5m_low,entry_upper_limit,
                entry_status,entry_executable,next_market_date,
                next_exit_first_5m_vwap,next_exit_to_1000_vwap,
                next_exit_first_5m_status,next_exit_to_1000_status,
                next_exit_first_5m_executable,next_exit_to_1000_executable
              FROM features ORDER BY date,code
            ) TO '{sql_path(outcomes_path)}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    metrics.update(
        {
            "expected_dates": expected_dates,
            "min_daily_coverage": coverage["min_daily_coverage"],
            "mean_daily_coverage": coverage["mean_daily_coverage"],
            "exact_1430_rate": exact_rate,
            "volume_consistency_rate": volume_rate,
        }
    )
    report = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "period": [SIGNAL_START, RAW_CUTOFF],
        "signal_end": SIGNAL_END,
        "collection": {
            "total_codes": len(read_json(input_dir / "codes.json")),
            "completed_codes": len(set(state.get("completed_codes", []))),
            "unresolved_codes": len(state.get("unresolved_codes", [])),
        },
        "metrics": metrics,
        "checks": checks,
        "cross_source": cross_rows.to_dict(orient="records"),
        "fingerprints": {
            "state": fingerprint(state_path),
            "universe": fingerprint(input_dir / "universe.parquet"),
            "industry": fingerprint(input_dir / "industry.parquet"),
            "trade_calendar": fingerprint(input_dir / "trade_calendar.parquet"),
            "cross_source_daily": fingerprint(cross_source),
        },
        "outputs": {
            "eligible_features": str(eligible_path) if eligible_path.exists() else None,
            "outcomes": str(outcomes_path) if outcomes_path.exists() else None,
        },
        "conclusion_scope": "5_MINUTE_BASIC_FILTER_ONLY",
        "independent_oos": False,
    }
    write_json(output / "quality-report.json", report)
    (output / "quality-report.md").write_text(markdown_quality(report), encoding="utf-8")
    print("RESULT=" + json.dumps({"status": status, "eligible_rows": metrics["eligible_rows"]}, ensure_ascii=False))


def prepare_enriched(input_dir: pathlib.Path, destination: pathlib.Path) -> None:
    eligible = input_dir / "eligible_features.parquet"
    outcomes = input_dir / "outcomes.parquet"
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.execute(
        f"""
        COPY (
          WITH joined AS (
            SELECT f.*,o.entry_next_5m_vwap,o.entry_next_5m_volume,
              o.entry_next_5m_amount,o.entry_status,o.entry_executable,
              o.next_market_date,o.next_exit_first_5m_vwap,o.next_exit_to_1000_vwap,
              o.next_exit_first_5m_status,o.next_exit_to_1000_status,
              o.next_exit_first_5m_executable,o.next_exit_to_1000_executable
            FROM read_parquet('{sql_path(eligible)}') f
            JOIN read_parquet('{sql_path(outcomes)}') o USING(source_id,code,date)
          ), industry_day AS (
            SELECT source_id,date,industry,
              median(ret1430) AS industry_ret_median,
              avg((ret1430>0)::INT) AS industry_up_ratio,
              avg((price1430>=vwap1430)::INT) AS industry_vwap_ratio,
              count(*) FILTER(WHERE ret1430>=3.0) AS industry_strong_count,
              sum(cum_amount1430) AS industry_amount1430
            FROM joined GROUP BY source_id,date,industry
          ), market_day AS (
            SELECT source_id,date,median(ret1430) AS market_ret_median,
              avg((ret1430>0)::INT) AS market_up_ratio,
              sum(cum_amount1430) AS market_amount1430,
              median(previous20_volatility) AS market_volatility_median
            FROM joined GROUP BY source_id,date
          ), industry_history AS (
            SELECT *,median(industry_amount1430) OVER(
              PARTITION BY source_id,industry ORDER BY date
              ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
            ) AS industry_amount_prev20_median
            FROM industry_day
          ), market_history AS (
            SELECT *,median(market_amount1430) OVER(
              PARTITION BY source_id ORDER BY date
              ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
            ) AS market_amount_prev20_median
            FROM market_day
          ), ranked_sector AS (
            SELECT *,percent_rank() OVER(
              PARTITION BY source_id,date ORDER BY industry_ret_median DESC
            ) AS sector_top_fraction
            FROM industry_history
          ), enriched AS (
            SELECT j.*,s.industry_ret_median,s.industry_up_ratio,
              s.industry_vwap_ratio,s.industry_strong_count,
              s.industry_amount1430,s.industry_amount_prev20_median,
              s.industry_amount1430/nullif(s.industry_amount_prev20_median,0)
                AS industry_activity_ratio,s.sector_top_fraction,
              m.market_ret_median,m.market_up_ratio,m.market_amount1430,
              m.market_amount_prev20_median,
              m.market_amount1430/nullif(m.market_amount_prev20_median,0)
                AS market_activity_ratio,m.market_volatility_median,
              percent_rank() OVER(
                PARTITION BY j.source_id,j.date,j.industry ORDER BY j.ret1430 DESC
              ) AS individual_top_fraction,
              percent_rank() OVER(
                PARTITION BY j.source_id,j.date ORDER BY j.cum_amount1430 DESC
              ) AS amount_top_fraction,
              percent_rank() OVER(
                PARTITION BY j.source_id,j.date ORDER BY j.float_market_cap1430
              ) AS market_cap_fraction
            FROM joined j JOIN ranked_sector s USING(source_id,date,industry)
            JOIN market_history m USING(source_id,date)
          )
          SELECT *,
            (next_exit_first_5m_vwap*(1-0.0010)*(1-0.0003-0.00001-0.0005)
              /(entry_next_5m_vwap*(1+0.0010)*(1+0.0003+0.00001))-1)
              AS net_first_worse,
            (next_exit_first_5m_vwap*(1-0.0020)*(1-0.0003-0.00001-0.0005)
              /(entry_next_5m_vwap*(1+0.0020)*(1+0.0003+0.00001))-1)
              AS net_first_extreme,
            (next_exit_to_1000_vwap*(1-0.0010)*(1-0.0003-0.00001-0.0005)
              /(entry_next_5m_vwap*(1+0.0010)*(1+0.0003+0.00001))-1)
              AS net_1000_worse
          FROM enriched
          WHERE entry_executable AND next_exit_first_5m_executable
            AND next_exit_to_1000_executable AND entry_next_5m_amount>0
        ) TO '{sql_path(destination)}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )


def rule_mask(frame: pd.DataFrame, config: dict, dropped: set[str]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    if "sector_strength" not in dropped:
        mask &= frame["sector_top_fraction"] <= config["sector_top"]
    if "sector_up_breadth" not in dropped:
        mask &= frame["industry_up_ratio"] >= config["sector_up_ratio"]
    if "sector_vwap_breadth" not in dropped:
        mask &= frame["industry_vwap_ratio"] >= config["sector_vwap_ratio"]
    if "sector_strong_count" not in dropped:
        mask &= frame["industry_strong_count"] >= config["sector_strong_count"]
    if "sector_activity" not in dropped:
        mask &= frame["industry_activity_ratio"] >= config["sector_activity"]
    if "individual_strength" not in dropped:
        mask &= frame["individual_top_fraction"] <= config["individual_top"]
    if "volume_ratio" not in dropped:
        mask &= frame["volume_ratio1430"] > config["volume_ratio"]
    if "turnover" not in dropped:
        lower, upper = config["turnover_band"]
        mask &= (frame["turnover1430_lower"] >= lower) & (frame["turnover1430_upper"] <= upper)
    if "amount_rank" not in dropped:
        mask &= frame["amount_top_fraction"] <= config["amount_top"]
    if "recent_strong" not in dropped:
        mask &= frame[f"recent_{config['recent_window']}_max_pct"] >= config["recent_pct"]
    if "continuous_volume" not in dropped:
        mask &= frame[f"volume_ma{config['volume_ma']}_d{config['volume_days']}_ok"]
    if "vwap_ratio" not in dropped:
        mask &= frame["above_vwap_5m_ratio"] >= config["vwap_ratio"]
    return mask.fillna(False)


def select_trades(frame: pd.DataFrame, config: dict, dropped: set[str]) -> tuple[pd.DataFrame, pd.Series]:
    candidates = frame.loc[rule_mask(frame, config, dropped)].copy()
    candidates = candidates[candidates["entry_next_5m_amount"] * 0.01 >= CAPITAL / MAX_HOLD]
    candidates.sort_values(
        ["date", "sector_top_fraction", "individual_top_fraction", "amount_top_fraction", "code"],
        inplace=True,
    )
    candidates = candidates.drop_duplicates(["date", "industry"], keep="first")
    selected = candidates.groupby("date", sort=False).head(MAX_HOLD).copy()
    all_dates = pd.Index(sorted(frame["date"].unique()), name="date")
    daily = selected.groupby("date")["net_first_worse"].sum().div(MAX_HOLD).reindex(all_dates, fill_value=0.0)
    return selected, daily


def max_drawdown(daily: pd.Series) -> float:
    if daily.empty:
        return math.nan
    equity = (1.0 + daily.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def one_sided_pvalue(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    if len(values) < 2 or np.std(values, ddof=1) == 0:
        return 1.0 if not len(values) or np.mean(values) <= 0 else 0.0
    return float(stats.ttest_1samp(values, 0.0, alternative="greater").pvalue)


def metrics(selected: pd.DataFrame, daily: pd.Series) -> dict:
    trades = selected["net_first_worse"].dropna().to_numpy(dtype=float)
    values = daily.to_numpy(dtype=float)
    positive = trades[trades > 0]
    negative = trades[trades < 0]
    return {
        "trades": int(len(trades)),
        "signal_days": int((daily != 0).sum()),
        "calendar_days": int(len(daily)),
        "mean_trade": float(np.mean(trades)) if len(trades) else math.nan,
        "median_trade": float(np.median(trades)) if len(trades) else math.nan,
        "win_rate": float(np.mean(trades > 0)) if len(trades) else math.nan,
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) and negative.sum() < 0 else math.nan,
        "mean_daily": float(np.mean(values)) if len(values) else math.nan,
        "sharpe": float(np.mean(values) / np.std(values, ddof=1) * math.sqrt(252)) if len(values) > 1 and np.std(values, ddof=1) > 0 else math.nan,
        "max_drawdown": max_drawdown(daily),
        "pvalue_one_sided": one_sided_pvalue(values),
    }


def evaluate(frame: pd.DataFrame, config: dict, dropped: set[str]) -> tuple[dict, pd.DataFrame, pd.Series]:
    selected, daily = select_trades(frame, config, dropped)
    return metrics(selected, daily), selected, daily


def monthly_metrics(frame: pd.DataFrame, config: dict, dropped: set[str]) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for month in (6, 7, 8):
        subset = frame[frame["date"].dt.month == month]
        output[str(month)] = evaluate(subset, config, dropped)[0]
    return output


def block_bootstrap(values: np.ndarray, samples: int = 2000, block: int = 5) -> dict:
    values = values[np.isfinite(values)]
    if not len(values):
        return {"mean": math.nan, "ci_low": math.nan, "ci_high": math.nan, "p_le_zero": 1.0}
    rng = np.random.default_rng(SEED)
    n = len(values)
    means = np.empty(samples)
    blocks_needed = math.ceil(n / block)
    for index in range(samples):
        picked: list[float] = []
        for start in rng.choice(np.arange(n), size=blocks_needed, replace=True):
            picked.extend(values[(start + offset) % n] for offset in range(block))
        means[index] = np.mean(picked[:n])
    return {
        "mean": float(np.mean(values)),
        "ci_low": float(np.quantile(means, 0.025)),
        "ci_high": float(np.quantile(means, 0.975)),
        "p_le_zero": float(np.mean(means <= 0)),
    }


def bh_adjust(pvalues: list[float]) -> list[float]:
    values = np.asarray([1.0 if not math.isfinite(value) else value for value in pvalues])
    order = np.argsort(values)
    adjusted = np.empty(len(values))
    running = 1.0
    for rank_index in range(len(values) - 1, -1, -1):
        original = order[rank_index]
        running = min(running, values[original] * len(values) / (rank_index + 1))
        adjusted[original] = min(running, 1.0)
    return adjusted.tolist()


def config_for_json(config: dict) -> dict:
    return {key: list(value) if isinstance(value, tuple) else value for key, value in config.items()}


def neighbors(parameter: str, value: Any) -> list[Any]:
    values = PARAMETERS[parameter]
    index = values.index(value)
    return [values[item] for item in range(max(index - 1, 0), min(index + 2, len(values)))]


def matched_control(frame: pd.DataFrame, selected: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    pool = frame[frame["entry_next_5m_amount"] * 0.01 >= CAPITAL / MAX_HOLD].copy()
    selected_keys = set(zip(selected["date"], selected["code"]))
    groups = {key: group for key, group in pool.groupby(["date", "industry"], sort=False)}
    rows = []
    for trade in selected.itertuples(index=False):
        group = groups.get((trade.date, trade.industry))
        if group is None:
            continue
        candidates = group[
            ~group.apply(lambda row: (row["date"], row["code"]) in selected_keys, axis=1)
        ].copy()
        if candidates.empty:
            continue
        distance = (
            (candidates["market_cap_fraction"] - trade.market_cap_fraction).abs()
            + (candidates["amount_top_fraction"] - trade.amount_top_fraction).abs()
            + (candidates["ret1430"] - trade.ret1430).abs() / 10.0
            + (candidates["turnover1430"] - trade.turnover1430).abs() / 10.0
        )
        chosen = candidates.loc[distance.idxmin()].copy()
        chosen["matched_signal_code"] = trade.code
        rows.append(chosen)
    controls = pd.DataFrame(rows)
    all_dates = pd.Index(sorted(frame["date"].unique()), name="date")
    daily = controls.groupby("date")["net_first_worse"].sum().div(MAX_HOLD).reindex(all_dates, fill_value=0.0) if not controls.empty else pd.Series(0.0, index=all_dates)
    return controls, daily


def concentration(selected: pd.DataFrame) -> dict:
    if selected.empty:
        return {"max_month_abs_share": 1.0, "max_industry_abs_share": 1.0, "top1_profit_share": 1.0}
    pnl = selected["net_first_worse"]
    total_abs = float(pnl.abs().sum())
    month_abs = selected.assign(month=selected["date"].dt.month).groupby("month")["net_first_worse"].apply(lambda values: values.abs().sum())
    industry_abs = selected.groupby("industry")["net_first_worse"].apply(lambda values: values.abs().sum())
    profits = pnl[pnl > 0].sort_values(ascending=False)
    top_n = max(1, math.ceil(len(pnl) * 0.01))
    return {
        "max_month_abs_share": float(month_abs.max() / total_abs) if total_abs else 1.0,
        "max_industry_abs_share": float(industry_abs.max() / total_abs) if total_abs else 1.0,
        "top1_profit_share": float(profits.head(top_n).sum() / profits.sum()) if len(profits) and profits.sum() else 1.0,
    }


def stratification(selected: pd.DataFrame) -> dict:
    if selected.empty:
        return {}
    frame = selected.copy()
    frame["month"] = frame["date"].dt.month
    frame["market_direction"] = np.where(frame["market_ret_median"] >= 0, "up", "down")
    frame["market_cap_layer"] = pd.cut(frame["market_cap_fraction"], [-math.inf, 0.25, 0.5, 0.75, math.inf], labels=["Q1", "Q2", "Q3", "Q4"]).astype(str)
    def summarize(column: str) -> list[dict]:
        return frame.groupby(column, dropna=False)["net_first_worse"].agg(["count", "mean", "median"]).reset_index().to_dict(orient="records")
    return {
        "month": summarize("month"),
        "market_direction": summarize("market_direction"),
        "market_cap_layer": summarize("market_cap_layer"),
        "industry": summarize("industry"),
    }


def choose_value(rows: list[dict], values: list[Any], fallback: Any) -> Any:
    eligible: list[tuple[float, int, Any]] = []
    for index, row in enumerate(rows):
        monthly = [item["mean_daily"] for item in row["monthly"].values()]
        positive_months = sum(math.isfinite(value) and value > 0 for value in monthly)
        neighbor_positive = any(
            0 <= candidate < len(rows) and rows[candidate]["full"]["mean_daily"] > 0
            for candidate in (index - 1, index + 1)
        )
        if row["full"]["mean_daily"] > 0 and positive_months >= 2 and neighbor_positive:
            score = row["full"]["mean_daily"] - 0.25 * float(np.nanstd(monthly))
            eligible.append((score, -index, row["value"]))
    if not eligible:
        return fallback
    return max(eligible)[2]


def markdown_develop(report: dict) -> str:
    return "\n".join(
        [
            "# 阶段 C R2 2026 开发期参数报告",
            "",
            f"- 状态：`{report['status']}`",
            f"- 交易数：{report['metrics']['trades']}",
            f"- 平均日净收益：{report['metrics']['mean_daily']:.6%}",
            f"- Bootstrap 95% CI：[{report['bootstrap']['ci_low']:.6%}, {report['bootstrap']['ci_high']:.6%}]",
            f"- 匹配对照增量 CI 下界：{report['matched_delta_bootstrap']['ci_low']:.6%}",
            f"- 参数：`{json.dumps(report['candidate'], ensure_ascii=False)}`",
            "",
            "本结果来自 2026-06-01 至 2026-08-24 开发与决策集，不是独立样本外证据。",
            "结论仅覆盖 5 分钟基础筛选层；1 分钟尾盘结构尚未验证。",
        ]
    ) + "\n"


def run_develop(input_dir: pathlib.Path, output: pathlib.Path) -> None:
    if output.exists():
        raise SystemExit(f"开发输出目录已存在：{output}")
    quality = read_json(input_dir / "quality-report.json")
    if quality.get("status") != "PASS_2026_DEVELOPMENT_DATA":
        raise SystemExit("2026 开发集数据门禁未通过")
    output.mkdir(parents=True)
    enriched = output / "enriched-development.parquet"
    prepare_enriched(input_dir, enriched)
    frame = pd.read_parquet(enriched)
    frame["date"] = pd.to_datetime(frame["date"])

    base_full, _, _ = evaluate(frame, BASE_CONFIG, set())
    base_monthly = monthly_metrics(frame, BASE_CONFIG, set())
    retained: set[str] = set()
    ablation_rows: list[dict] = []
    for condition in CONDITIONS:
        result, _, _ = evaluate(frame, BASE_CONFIG, {condition})
        monthly = monthly_metrics(frame, BASE_CONFIG, {condition})
        full_delta = base_full["mean_daily"] - result["mean_daily"]
        monthly_deltas = {
            month: base_monthly[month]["mean_daily"] - monthly[month]["mean_daily"]
            for month in base_monthly
        }
        keep = full_delta > 0 and sum(value > 0 for value in monthly_deltas.values()) >= 2
        if keep:
            retained.add(condition)
        ablation_rows.append(
            {"condition": condition, "full_delta": full_delta, **{f"month_{key}_delta": value for key, value in monthly_deltas.items()}, "retained": keep}
        )
    dropped = set(CONDITIONS) - retained
    config = dict(BASE_CONFIG)
    sensitivity: list[dict] = []
    pvalues: list[float] = []
    for parameter, values in PARAMETERS.items():
        if PARAM_CONDITION[parameter] not in retained:
            continue
        candidates = []
        for value in values:
            candidate = dict(config)
            candidate[parameter] = value
            full, _, _ = evaluate(frame, candidate, dropped)
            monthly = monthly_metrics(frame, candidate, dropped)
            candidates.append({"value": value, "full": full, "monthly": monthly})
            pvalues.append(full["pvalue_one_sided"])
            sensitivity.append(
                {"parameter": parameter, "value": json.dumps(value), "mean_daily": full["mean_daily"], "trades": full["trades"], "positive_months": sum(item["mean_daily"] > 0 for item in monthly.values()), "pvalue": full["pvalue_one_sided"]}
            )
        config[parameter] = choose_value(candidates, values, config[parameter])

    combination_rows = []
    for first, second in (("sector_top", "sector_up_ratio"), ("volume_ratio", "volume_days"), ("turnover_band", "amount_top")):
        if PARAM_CONDITION[first] not in retained or PARAM_CONDITION[second] not in retained:
            continue
        for first_value in neighbors(first, config[first]):
            for second_value in neighbors(second, config[second]):
                candidate = dict(config)
                candidate[first] = first_value
                candidate[second] = second_value
                result, _, _ = evaluate(frame, candidate, dropped)
                combination_rows.append({"first": first, "second": second, "first_value": json.dumps(first_value), "second_value": json.dumps(second_value), "mean_daily": result["mean_daily"], "trades": result["trades"]})

    result_metrics, selected, daily = evaluate(frame, config, dropped)
    monthly = monthly_metrics(frame, config, dropped)
    bootstrap = block_bootstrap(daily.to_numpy(dtype=float))
    matched, matched_daily = matched_control(frame, selected)
    selected_aligned, matched_aligned = daily.align(matched_daily, join="outer", fill_value=0.0)
    matched_delta = block_bootstrap((selected_aligned - matched_aligned).to_numpy(dtype=float))
    extreme_daily = selected.groupby("date")["net_first_extreme"].sum().div(MAX_HOLD).reindex(daily.index, fill_value=0.0)
    extreme_bootstrap = block_bootstrap(extreme_daily.to_numpy(dtype=float))
    concentration_result = concentration(selected)
    adjacent = []
    for parameter, current in config.items():
        if parameter not in PARAMETERS or PARAM_CONDITION[parameter] not in retained:
            continue
        rows = []
        for value in neighbors(parameter, current):
            if value == current:
                continue
            candidate = dict(config)
            candidate[parameter] = value
            full, _, _ = evaluate(frame, candidate, dropped)
            month_result = monthly_metrics(frame, candidate, dropped)
            stable = full["mean_daily"] > 0 and sum(item["mean_daily"] > 0 for item in month_result.values()) >= 2
            rows.append({"value": value, "metrics": full, "monthly": month_result, "stable": stable})
        adjacent.append({"parameter": parameter, "current": current, "neighbors": rows, "stable": any(row["stable"] for row in rows)})
    final_pvalue = result_metrics["pvalue_one_sided"]
    qvalues = bh_adjust(pvalues + [final_pvalue])
    final_qvalue = qvalues[-1]
    positive_months = sum(item["mean_daily"] > 0 for item in monthly.values())
    gates = {
        "positive_mean": result_metrics["mean_daily"] > 0,
        "positive_months": positive_months >= 2,
        "bootstrap": bootstrap["ci_low"] >= 0,
        "matched_delta": matched_delta["ci_low"] >= 0,
        "multiple_tests": final_qvalue <= 0.10,
        "adjacent_stability": bool(adjacent) and all(item["stable"] for item in adjacent),
        "extreme_cost": extreme_bootstrap["ci_high"] >= 0,
        "concentration": max(concentration_result.values()) < 0.50,
    }
    status = "BASIC_PARAMETERS_DECIDED" if all(gates.values()) else "NO_QUALIFIED_BASIC_PARAMETER_SET"
    report = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "candidate": config_for_json(config),
        "retained_conditions": sorted(retained),
        "dropped_conditions": sorted(dropped),
        "base_metrics": base_full,
        "base_monthly": base_monthly,
        "metrics": result_metrics,
        "monthly": monthly,
        "bootstrap": bootstrap,
        "matched_metrics": metrics(matched, matched_daily),
        "matched_delta_bootstrap": matched_delta,
        "extreme_cost_bootstrap": extreme_bootstrap,
        "concentration": concentration_result,
        "stratification": stratification(selected),
        "adjacent_parameter_results": adjacent,
        "final_pvalue": final_pvalue,
        "final_qvalue": final_qvalue,
        "gates": gates,
        "independent_oos": False,
        "conclusion_scope": "5_MINUTE_BASIC_FILTER_ONLY",
        "one_minute_tail_structure": "NOT_VALIDATED",
    }
    write_json(output / "development-report.json", report)
    (output / "development-report.md").write_text(markdown_develop(report), encoding="utf-8")
    pd.DataFrame(ablation_rows).to_csv(output / "ablation.csv", index=False)
    sensitivity_frame = pd.DataFrame(sensitivity)
    if not sensitivity_frame.empty:
        sensitivity_frame["qvalue"] = bh_adjust(sensitivity_frame["pvalue"].tolist())
    sensitivity_frame.to_csv(output / "sensitivity.csv", index=False)
    pd.DataFrame(combination_rows).to_csv(output / "combination-tests.csv", index=False)
    selected.to_parquet(output / "selected-trades.parquet", index=False)
    daily.rename("net_return").to_frame().to_parquet(output / "daily-returns.parquet")
    matched.to_parquet(output / "matched-controls.parquet", index=False)
    write_json(
        output / "frozen-basic-parameters.json",
        {
            "experiment_id": EXPERIMENT_ID,
            "status": status,
            "config": config_for_json(config),
            "retained_conditions": sorted(retained),
            "dropped_conditions": sorted(dropped),
            "development_period": [SIGNAL_START, RAW_CUTOFF],
            "independent_oos": False,
            "input_quality_report_sha256": hashlib.sha256((input_dir / "quality-report.json").read_bytes()).hexdigest(),
        },
    )
    print("RESULT=" + json.dumps({"status": status, "trades": result_metrics["trades"], "mean_daily": result_metrics["mean_daily"], "ci_low": bootstrap["ci_low"]}, ensure_ascii=False))


def main() -> None:
    args = parse_args()
    if args.phase == "audit":
        run_audit(
            pathlib.Path(args.input).expanduser().resolve(),
            pathlib.Path(args.output).expanduser().resolve(),
            pathlib.Path(args.cross_source_daily).expanduser().resolve(),
        )
    else:
        run_develop(
            pathlib.Path(args.input).expanduser().resolve(),
            pathlib.Path(args.output).expanduser().resolve(),
        )


if __name__ == "__main__":
    main()
