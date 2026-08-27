#!/usr/bin/env python3
"""Apply frozen R2 candidate parameters to one forward 5-minute screening day."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

import duckdb
import pandas as pd


CAPITAL = 1_000_000.0
MAX_HOLD = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--bars-glob", required=True)
    parser.add_argument("--daily-glob", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--industry", required=True)
    parser.add_argument("--development-enriched", required=True)
    parser.add_argument("--volume-state", required=True)
    parser.add_argument("--parameters", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def records(frame: pd.DataFrame) -> list[dict]:
    return [
        {key: json_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def main() -> None:
    args = parse_args()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Output already exists; refusing to overwrite: {output}")
    output.mkdir(parents=True)

    parameters = json.loads(pathlib.Path(args.parameters).read_text(encoding="utf-8"))
    config = parameters["config"]
    retained = set(parameters["retained_conditions"])
    expected = {
        "continuous_volume",
        "individual_strength",
        "sector_activity",
        "sector_vwap_breadth",
        "turnover",
        "vwap_ratio",
    }
    if retained != expected:
        raise SystemExit(f"Unexpected retained conditions: {sorted(retained)}")
    volume_state = json.loads(pathlib.Path(args.volume_state).read_text(encoding="utf-8"))
    if volume_state.get("status") != "COMPLETE":
        raise SystemExit("Volume prefilter is not COMPLETE")

    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.execute("CREATE TEMP TABLE volume_pass(code VARCHAR)")
    connection.executemany(
        "INSERT INTO volume_pass VALUES (?)",
        [(code,) for code in volume_state["volume_pass_codes"]],
    )

    connection.execute(
        f"""
        CREATE TEMP TABLE aggregates AS
        WITH ordered AS (
          SELECT *,
            sum(volume) OVER(PARTITION BY code,date ORDER BY time ROWS UNBOUNDED PRECEDING) AS cv,
            sum(amount) OVER(PARTITION BY code,date ORDER BY time ROWS UNBOUNDED PRECEDING) AS ca
          FROM read_parquet('{args.bars_glob}')
        )
        SELECT code,date,count(*) AS bar_count,count(DISTINCT time) AS distinct_bars,
          arg_max(close,time) FILTER(WHERE time<='1430') AS price1430,
          sum(volume) FILTER(WHERE time<='1430') AS cum_volume1430,
          sum(amount) FILTER(WHERE time<='1430') AS cum_amount1430,
          sum(amount) FILTER(WHERE time<='1430')
            /nullif(sum(volume) FILTER(WHERE time<='1430'),0) AS vwap1430,
          avg((close>=ca/nullif(cv,0))::INT)
            FILTER(WHERE time BETWEEN '1000' AND '1430') AS above_vwap_5m_ratio,
          max(volume) FILTER(WHERE time='1435') AS entry_volume,
          max(amount) FILTER(WHERE time='1435') AS entry_amount,
          max(low) FILTER(WHERE time='1435') AS entry_low,
          max(high) FILTER(WHERE time='1435') AS entry_high,
          max(amount) FILTER(WHERE time='1435')
            /nullif(max(volume) FILTER(WHERE time='1435'),0) AS entry_vwap,
          sum(volume) AS full_day_volume,sum(amount) AS full_day_amount
        FROM ordered GROUP BY code,date
        """
    )

    connection.execute(
        f"""
        CREATE TEMP TABLE current_base AS
        WITH prior AS (
          SELECT * FROM read_parquet('{args.daily_glob}') WHERE date='2026-08-24'
        ), current_universe AS (
          SELECT CASE WHEN code>='600000' THEN 'sh.'||code ELSE 'sz.'||code END AS code,
            name,trade_status,is_st_name
          FROM read_parquet('{args.universe}') WHERE date='{args.date}'
        ), current_industry AS (
          SELECT CASE WHEN code>='600000' THEN 'sh.'||code ELSE 'sz.'||code END AS code,
            industry,classification
          FROM read_parquet('{args.industry}') WHERE date='{args.date}'
        )
        SELECT a.*,p.close AS preclose,p.volume AS prior_day_volume,
          p.turnover_full_day AS prior_day_turnover,
          p.volume/nullif(p.turnover_full_day/100.0,0) AS historical_float_shares,
          a.cum_volume1430/nullif(p.volume/(p.turnover_full_day/100.0),0)*100
            AS turnover1430_prior_float,
          (a.price1430/p.close-1)*100 AS ret1430,
          u.name,u.trade_status AS current_trade_status,u.is_st_name,
          i.industry,i.classification
        FROM aggregates a JOIN prior p USING(code)
        JOIN current_universe u USING(code) JOIN current_industry i USING(code)
        WHERE a.date='{args.date}' AND a.bar_count=48 AND a.distinct_bars=48
          AND u.trade_status=1 AND NOT u.is_st_name
          AND p.trade_status=1 AND NOT p.is_st AND p.listing_market_days_prior>=60
          AND p.recent_30_complete AND p.previous20_complete
          AND p.volume_ma120_d5_complete
          AND p.volume>0 AND p.turnover_full_day>0
          AND trim(i.industry)<>''
        """
    )

    connection.execute(
        f"""
        CREATE TEMP TABLE industry_prior_day AS
        WITH prior_industry AS (
          SELECT CASE WHEN code>='600000' THEN 'sh.'||code ELSE 'sz.'||code END AS code,
            industry
          FROM read_parquet('{args.industry}') WHERE date='2026-08-24'
        )
        SELECT i.industry,a.date,
          median((a.price1430/d.preclose-1)*100) AS industry_ret_median,
          avg(((a.price1430/d.preclose-1)*100>0)::INT) AS industry_up_ratio,
          avg((a.price1430>=a.vwap1430)::INT) AS industry_vwap_ratio,
          count(*) FILTER(WHERE (a.price1430/d.preclose-1)*100>=3) AS industry_strong_count,
          sum(a.cum_amount1430) AS industry_amount1430
        FROM aggregates a JOIN read_parquet('{args.daily_glob}') d USING(code,date)
        JOIN prior_industry i USING(code)
        WHERE a.date='2026-08-24' AND a.bar_count=48 AND a.distinct_bars=48
          AND d.trade_status=1 AND NOT d.is_st AND d.listing_market_days_prior>=60
          AND d.recent_30_complete AND d.previous20_complete
          AND d.volume_ma120_d5_complete
          AND abs(a.full_day_volume-d.volume)/d.volume<=0.02
          AND trim(i.industry)<>''
        GROUP BY i.industry,a.date
        """
    )

    connection.execute(
        f"""
        CREATE TEMP TABLE enriched AS
        WITH industry_current AS (
          SELECT industry,median(ret1430) AS industry_ret_median,
            avg((ret1430>0)::INT) AS industry_up_ratio,
            avg((price1430>=vwap1430)::INT) AS industry_vwap_ratio,
            count(*) FILTER(WHERE ret1430>=3) AS industry_strong_count,
            sum(cum_amount1430) AS industry_amount1430
          FROM current_base GROUP BY industry
        ), history AS (
          SELECT DISTINCT industry,date,industry_amount1430
          FROM read_parquet('{args.development_enriched}') WHERE date<'2026-08-24'
          UNION ALL
          SELECT industry,date,industry_amount1430 FROM industry_prior_day
        ), numbered AS (
          SELECT *,row_number() OVER(PARTITION BY industry ORDER BY date DESC) AS rn
          FROM history
        ), baseline AS (
          SELECT industry,median(industry_amount1430) AS industry_amount_prev20_median,
            count(*) AS baseline_days
          FROM numbered WHERE rn<=20 GROUP BY industry
        ), sectors AS (
          SELECT c.*,b.industry_amount_prev20_median,b.baseline_days,
            c.industry_amount1430/nullif(b.industry_amount_prev20_median,0)
              AS industry_activity_ratio,
            percent_rank() OVER(ORDER BY c.industry_ret_median DESC) AS sector_top_fraction
          FROM industry_current c LEFT JOIN baseline b USING(industry)
        ), joined AS (
          SELECT c.*,s.* EXCLUDE(industry),
            percent_rank() OVER(PARTITION BY c.industry ORDER BY c.ret1430 DESC)
              AS individual_top_fraction,
            percent_rank() OVER(ORDER BY c.cum_amount1430 DESC) AS amount_top_fraction
          FROM current_base c JOIN sectors s USING(industry)
        )
        SELECT *,code IN (SELECT code FROM volume_pass) AS continuous_volume_pass,
          entry_volume>0 AND entry_low<round(preclose*1.10,2) AS entry_executable_prior
        FROM joined
        """
    )

    lower, upper = config["turnover_band"]
    required_entry_amount = CAPITAL / MAX_HOLD / 0.01
    connection.execute(
        f"""
        CREATE TEMP TABLE audited AS
        SELECT *,
          industry_vwap_ratio>={float(config['sector_vwap_ratio'])} AS pass_sector_vwap,
          industry_activity_ratio>={float(config['sector_activity'])} AS pass_sector_activity,
          individual_top_fraction<={float(config['individual_top'])} AS pass_individual_strength,
          turnover1430_prior_float BETWEEN {float(lower)} AND {float(upper)} AS pass_turnover,
          continuous_volume_pass AS pass_continuous_volume,
          above_vwap_5m_ratio>={float(config['vwap_ratio'])} AS pass_vwap_ratio,
          entry_amount>={required_entry_amount} AS pass_entry_liquidity,
          entry_executable_prior AS pass_entry_executable
        FROM enriched
        """
    )
    gate_names = [
        "pass_sector_vwap",
        "pass_sector_activity",
        "pass_individual_strength",
        "pass_turnover",
        "pass_continuous_volume",
        "pass_vwap_ratio",
        "pass_entry_liquidity",
        "pass_entry_executable",
    ]
    all_rules = " AND ".join(gate_names)
    all_except_liquidity = " AND ".join(name for name in gate_names if name != "pass_entry_liquidity")
    all_except_turnover = " AND ".join(name for name in gate_names if name != "pass_turnover")
    all_except_both = " AND ".join(
        name for name in gate_names if name not in {"pass_entry_liquidity", "pass_turnover"}
    )

    enriched_path = output / "enriched-forward.parquet"
    connection.execute(f"COPY audited TO '{enriched_path}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    connection.execute(
        f"COPY (SELECT * FROM audited ORDER BY code) TO '{output / 'rule-audit.csv'}' "
        "(HEADER,DELIMITER ',')"
    )
    closest = connection.execute(
        f"""
        SELECT * FROM audited WHERE {all_except_liquidity}
        ORDER BY entry_amount DESC,sector_top_fraction,individual_top_fraction,
          amount_top_fraction,code
        """
    ).fetchdf()
    closest.to_csv(output / "closest-before-liquidity.csv", index=False)
    candidates = connection.execute(
        f"""
        SELECT * FROM audited WHERE {all_rules}
        ORDER BY sector_top_fraction,individual_top_fraction,amount_top_fraction,code
        """
    ).fetchdf()
    selected = candidates.drop_duplicates(["industry"], keep="first").head(MAX_HOLD).copy()
    candidates.to_csv(output / "eligible-candidates.csv", index=False)
    selected.to_csv(output / "selected-candidates.csv", index=False)

    sequential: dict[str, int] = {}
    cumulative: list[str] = []
    for name in gate_names:
        cumulative.append(name)
        sequential[name] = int(
            connection.execute(
                "SELECT count(*) FROM audited WHERE " + " AND ".join(cumulative)
            ).fetchone()[0]
        )
    report = {
        "experiment_id": parameters["experiment_id"],
        "screen_date": args.date,
        "as_of_time": "14:35",
        "status": "OBSERVATION_CANDIDATES_FOUND" if len(selected) else "NO_5M_BASIC_OBSERVATION_CANDIDATE",
        "parameter_status": parameters["status"],
        "retained_conditions": sorted(retained),
        "config": config,
        "base_cross_section_rows": int(connection.execute("SELECT count(*) FROM audited").fetchone()[0]),
        "sequential_gate_counts": sequential,
        "all_rule_candidates": len(candidates),
        "selected_candidates": len(selected),
        "all_except_liquidity": int(
            connection.execute(f"SELECT count(*) FROM audited WHERE {all_except_liquidity}").fetchone()[0]
        ),
        "all_except_turnover": int(
            connection.execute(f"SELECT count(*) FROM audited WHERE {all_except_turnover}").fetchone()[0]
        ),
        "all_except_turnover_and_liquidity": int(
            connection.execute(f"SELECT count(*) FROM audited WHERE {all_except_both}").fetchone()[0]
        ),
        "entry_liquidity_required_amount": required_entry_amount,
        "turnover_basis": "prior_day_baostock_float_shares; exact signal-day turnover required only if candidates remain",
        "closest_before_liquidity": records(closest),
        "selected": records(selected),
        "data_sources": {
            "intraday": "Baostock 5-minute bars, 2026-08-24..2026-08-25",
            "daily_history": "R2 Baostock daily artifacts plus exact 120-day checks",
            "universe_and_industry": "Baostock point-in-time snapshots at 2026-08-25",
        },
        "independent_forward_day": True,
        "independent_oos_claim": False,
        "conclusion_scope": "5_MINUTE_BASIC_FILTER_ONLY",
        "one_minute_tail_structure": "NOT_VALIDATED",
    }
    (output / "scan-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "RESULT="
        + json.dumps(
            {
                "status": report["status"],
                "base_rows": report["base_cross_section_rows"],
                "all_rules": report["all_rule_candidates"],
                "closest_before_liquidity": report["all_except_liquidity"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
