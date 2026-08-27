#!/usr/bin/env python3
"""审计 Baostock 5 分钟聚合数据并生成冻结的基础特征数据集。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import pathlib
import urllib.parse
import urllib.request

import duckdb


TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_SAMPLE_CODES = ("sh.600000", "sh.600519", "sh.603007", "sz.000001", "sz.002415")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--reuse-audited",
        action="store_true",
        help="复用输出目录中已生成的 audited_features.parquet，仅重跑门禁与报告",
    )
    return parser.parse_args()


def sql_path(path: pathlib.Path) -> str:
    return str(path).replace("'", "''")


def scalar(connection: duckdb.DuckDBPyConnection, query: str, params=None):
    return connection.execute(query, params or []).fetchone()[0]


def row_dict(connection: duckdb.DuckDBPyConnection, query: str, params=None) -> dict:
    cursor = connection.execute(query, params or [])
    values = cursor.fetchone()
    return dict(zip([item[0] for item in cursor.description], values))


def source_fingerprint(root: pathlib.Path) -> tuple[str, int, int]:
    paths = sorted((root / "features").glob("part-*.parquet"))
    paths.extend(root / name for name in ("codes.json", "state.json", "universe.parquet", "industry.parquet"))
    digest = hashlib.sha256()
    total_bytes = 0
    for path in paths:
        relative = str(path.relative_to(root)).encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        size = path.stat().st_size
        total_bytes += size
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest(), len(paths), total_bytes


def fetch_tencent_daily(code: str) -> dict[str, dict]:
    symbol = code.replace(".", "")
    params = {
        "param": f"{symbol},day,2023-12-15,2024-12-31,400,bfq",
    }
    request = urllib.request.Request(
        TENCENT_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://stock.qq.com/"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise RuntimeError(f"Tencent response: {payload.get('code')} {payload.get('msg')}")
    node = payload.get("data", {}).get(symbol, {})
    rows = node.get("day")
    if not isinstance(rows, list):
        raise RuntimeError("Tencent unadjusted daily rows missing")
    output = {}
    previous_close = math.nan
    for raw in rows:
        date, open_price, close, high, low, volume_lots = raw[:6]
        corporate_action = raw[6] if len(raw) > 6 and isinstance(raw[6], dict) else None
        output[date] = {
            "open": float(open_price),
            "close": float(close),
            "high": float(high),
            "low": float(low),
            "volume_shares": float(volume_lots) * 100.0,
            "previous_close": previous_close,
            "corporate_action": corporate_action,
        }
        previous_close = float(close)
    return output


def crosscheck_tencent(connection: duckdb.DuckDBPyConnection, features_glob: str) -> dict:
    checks = []
    errors = []
    for code in TENCENT_SAMPLE_CODES:
        try:
            tencent = fetch_tencent_daily(code)
        except Exception as exc:  # noqa: BLE001
            errors.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})
            continue
        local_rows = connection.execute(
            """
            SELECT code,date,price1430,preclose,
                   float_shares_inferred*daily_turnover/100.0 AS reconstructed_daily_volume
            FROM read_parquet(?) WHERE code=? ORDER BY date
            """,
            [features_glob, code],
        ).fetchall()
        for _, date, price1430, preclose, daily_volume in local_rows:
            remote = tencent.get(date)
            if remote is None:
                continue
            price_in_range = (
                price1430 is not None
                and math.isfinite(price1430)
                and remote["low"] - 0.011 <= price1430 <= remote["high"] + 0.011
            )
            preclose_match = (
                math.isnan(remote["previous_close"])
                or abs(preclose - remote["previous_close"]) <= 0.011
            )
            preclose_explained_by_corporate_action = (
                not preclose_match and remote["corporate_action"] is not None
            )
            denominator = max(remote["volume_shares"], 1.0)
            volume_relative_error = abs(daily_volume - remote["volume_shares"]) / denominator
            checks.append(
                {
                    "code": code,
                    "date": date,
                    "price_in_daily_range": price_in_range,
                    "preclose_match": preclose_match,
                    "preclose_explained_by_corporate_action": (
                        preclose_explained_by_corporate_action
                    ),
                    "volume_relative_error": volume_relative_error,
                }
            )
    matched_by_code = {
        code: sum(item["code"] == code for item in checks) for code in TENCENT_SAMPLE_CODES
    }
    return {
        "source": "Tencent unadjusted daily kline",
        "sample_codes": list(TENCENT_SAMPLE_CODES),
        "matched_stock_days": len(checks),
        "matched_stock_days_by_code": matched_by_code,
        "price_range_mismatches": sum(not item["price_in_daily_range"] for item in checks),
        "preclose_mismatches": sum(not item["preclose_match"] for item in checks),
        "preclose_corporate_action_rows": sum(
            item["preclose_explained_by_corporate_action"] for item in checks
        ),
        "preclose_unexplained_mismatches": sum(
            not item["preclose_match"]
            and not item["preclose_explained_by_corporate_action"]
            for item in checks
        ),
        "volume_mismatches_over_0_5pct": sum(
            item["volume_relative_error"] > 0.005 for item in checks
        ),
        "max_volume_relative_error": max(
            (item["volume_relative_error"] for item in checks), default=None
        ),
        "errors": errors,
        "limitation": "腾讯免费接口未提供对应历史 14:30 成交额和 VWAP，无法做第二来源精确分钟交叉核对。",
    }


def create_audited_dataset(
    connection: duckdb.DuckDBPyConnection,
    root: pathlib.Path,
    destination: pathlib.Path,
) -> None:
    features = sql_path(root / "features" / "*.parquet")
    industry = sql_path(root / "industry.parquet")
    target = sql_path(destination)
    feature_columns = {
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)",
            [str(root / "features" / "*.parquet")],
        ).fetchall()
    }
    intraday_complete_expression = (
        "coalesce(exact_1430_complete,false)"
        if "exact_1430_complete" in feature_columns
        else (
            "bar_count=48 AND first_bar_time='0935' AND last_bar_time='1500' "
            "AND strength_5m_count=37"
        )
    )
    query = f"""
    COPY (
      WITH market_dates_base AS (
        SELECT DISTINCT date FROM read_parquet('{features}')
        UNION SELECT '2025-01-02'
      ), market_dates AS (
        SELECT date, lead(date) OVER (ORDER BY date) AS next_market_date
        FROM market_dates_base
      ), shares AS (
        SELECT f.*,
          last_value(
            CASE WHEN isfinite(float_shares_inferred) AND float_shares_inferred>0
                 THEN float_shares_inferred END IGNORE NULLS
          ) OVER (
            PARTITION BY code ORDER BY date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS float_shares_asof,
          last_value(
            CASE WHEN isfinite(float_shares_inferred) AND float_shares_inferred>0
                 THEN date END IGNORE NULLS
          ) OVER (
            PARTITION BY code ORDER BY date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS float_shares_asof_date
        FROM read_parquet('{features}') f
      ), ind AS (
        SELECT snapshot_date,update_date,code,industry,classification
        FROM read_parquet('{industry}')
      ), mapped AS (
        SELECT s.*,i.snapshot_date AS industry_snapshot_date,
               i.update_date AS industry_update_date,
               i.industry,i.classification,m.next_market_date
        FROM shares s
        ASOF LEFT JOIN ind i ON s.code=i.code AND s.date>=i.snapshot_date
        JOIN market_dates m USING(date)
      ), flags AS (
        SELECT *,
          {intraday_complete_expression} AS intraday_complete,
          trade_status=1 AS current_tradeable,
          isfinite(price1430) AND price1430>0
            AND isfinite(cum_volume1430) AND cum_volume1430>0
            AND isfinite(cum_amount1430) AND cum_amount1430>0
            AND isfinite(vwap1430) AND vwap1430>0
            AND isfinite(preclose) AND preclose>0
            AND isfinite(prev5_volume) AND prev5_volume>0
            AND isfinite(volume_ratio1430) AND volume_ratio1430>0
            AND isfinite(float_shares_asof) AND float_shares_asof>0
              AS feature_values_valid,
          recent20_complete AND volume3_complete AS history_complete,
          industry IS NOT NULL AND trim(industry)<>'' AS industry_valid,
          coalesce(next_date=next_market_date,false) AS next_session_exact,
          coalesce(next_date=next_market_date,false)
            AND isfinite(next_exit_first_5m_vwap) AND next_exit_first_5m_vwap>0
              AS outcome_first_available,
          coalesce(next_date=next_market_date,false)
            AND isfinite(next_exit_to_1000_vwap) AND next_exit_to_1000_vwap>0
              AS outcome_1000_available
        FROM mapped
      ), final AS (
        SELECT
          * EXCLUDE (
            float_shares_inferred,daily_turnover,turnover1430_inferred,
            next_exit_first_5m_vwap,next_exit_to_1000_vwap
          ),
          float_shares_inferred AS raw_same_day_float_shares_inferred,
          daily_turnover AS raw_full_day_turnover,
          turnover1430_inferred AS raw_same_day_turnover1430,
          next_exit_first_5m_vwap AS raw_next_exit_first_5m_vwap,
          next_exit_to_1000_vwap AS raw_next_exit_to_1000_vwap,
          cum_volume1430/float_shares_asof*100.0 AS turnover1430_asof,
          CASE WHEN outcome_first_available THEN next_exit_first_5m_vwap END
            AS next_exit_first_5m_vwap_safe,
          CASE WHEN outcome_1000_available THEN next_exit_to_1000_vwap END
            AS next_exit_to_1000_vwap_safe,
          intraday_complete AND current_tradeable AND feature_values_valid
            AND history_complete AND industry_valid
            AND NOT is_st AND listing_days_prior>=60
              AS strategy_universe_eligible,
          CASE
            WHEN coalesce(next_date,'')='' OR next_market_date IS NULL
              THEN 'NEXT_SESSION_MISSING'
            WHEN next_date<>next_market_date THEN 'NEXT_SESSION_UNTRADABLE'
            WHEN NOT outcome_first_available AND NOT outcome_1000_available
              THEN 'NEXT_SESSION_NO_EXIT_PRICE'
            WHEN NOT outcome_first_available THEN 'FIRST_5M_NO_EXIT_PRICE'
            WHEN NOT outcome_1000_available THEN 'TO_1000_NO_EXIT_PRICE'
            ELSE 'AVAILABLE'
          END AS outcome_status
        FROM flags
      )
      SELECT * FROM final
    ) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    connection.execute(query)


def markdown_report(report: dict) -> str:
    basic = report["basic"]
    audited = report["audited"]
    cross = report["cross_source"]
    gates = report["gates"]
    lines = [
        "# 2024 年 Baostock 5 分钟聚合数据质量审计",
        "",
        f"- 审计状态：**{report['status']}**",
        f"- 生成时间：{report['created_at']}",
        f"- 源数据指纹：`{report['source']['sha256']}`",
        f"- 股票状态：{basic['completed_codes']} / {basic['total_codes']} 已完成",
        f"- 原始股票日：{basic['row_count']:,}",
        f"- 门禁前暂算基础股票日：{audited['eligible_rows']:,}",
        f"- 冻结数据集：{'已生成' if report['frozen_dataset_generated'] else '未生成（硬门禁未通过）'}",
        "",
        "## 门禁结果",
        "",
        "| 门禁 | 状态 | 证据 |",
        "|---|---|---|",
    ]
    for gate in gates:
        lines.append(f"| {gate['name']} | {gate['status']} | {gate['evidence']} |")
    failed_gates = [gate for gate in gates if gate["status"] == "FAIL"]
    if failed_gates:
        lines.extend(["", "## 阻断项", ""])
        lines.extend(f"- {gate['name']}：{gate['evidence']}" for gate in failed_gates)
    lines.extend(
        [
            "",
            "## 关键发现与修正",
            "",
            f"- 原始数据无重复股票日；共 {basic['duplicate_rows']} 条重复。",
            f"- {basic['incomplete_intraday_rows']} 个股票日未通过{basic['intraday_completeness_basis']}，门禁前暂算基础池中排除。",
            f"- {basic['nontrade_status_rows']} 个股票日交易状态异常，门禁前暂算基础池中排除。",
            f"- {basic['missing_industry_rows']} 个股票日没有可用的历史行业映射，门禁前暂算基础池中排除。",
            f"- 状态文件完成 {basic['completed_codes']} 只代码，但实际有观测的是 {basic['feature_codes']} 只；{basic['completed_without_feature_rows']} 只全期无股票日记录。",
            f"- {basic['delayed_next_rows']} 个股票日的原始次日字段跳过市场下一交易日（可能是停牌或分钟行情缺失）；日期对齐退出字段已置空，并标记 `NEXT_SESSION_UNTRADABLE`。",
            f"- {basic['missing_next_rows']} 个股票日没有下一交易日期；日期对齐退出字段已置空。",
            "- 原始同日换手率依赖当日完整成交量，不能用于 14:30 时点回测；审计集另算了此前最后一个有效历史行的流通股本口径。",
            "- 上一历史行股本只消除了直接读取同日收盘数据；由于分钟量与日线量存在不可能关系，且未核验股本变更生效日，当前 `turnover1430_asof` 仍未获准用于分析。",
            "- 不可退出样本不会静默删除，保留 `outcome_status` 用于尾部风险统计。",
            f"- 门禁前暂算基础池仍保留首个退出窗口不可用 {audited['eligible_without_first_exit_rows']} 条、10:00 前退出窗口不可用 {audited['eligible_without_1000_exit_rows']} 条，用于尾部风险统计。",
            "- 当前滚动历史字段的停牌污染统计只覆盖已落盘的 2024 年行；采集器使用但未落盘的 2023 年回看期无法反向审计，因此报告数字是下界。",
            "",
            "## 第二来源抽样",
            "",
            f"- 来源：{cross['source']}",
            f"- 匹配股票日：{cross['matched_stock_days']}",
            f"- 14:30 价格超出当日日线高低范围：{cross['price_range_mismatches']}",
            f"- 前收盘价不一致：{cross['preclose_mismatches']}",
            f"- 其中腾讯除权除息信息可解释：{cross['preclose_corporate_action_rows']}",
            f"- 未解释的前收盘价差异：{cross['preclose_unexplained_mismatches']}",
            f"- 日成交量误差超过 0.5%：{cross['volume_mismatches_over_0_5pct']}",
            f"- 限制：{cross['limitation']}",
            "",
            "## 审计边界与后续冻结要求",
            "",
            "- 只有全部硬门禁通过后才允许生成 `eligible_features.parquet`；它也只代表基础筛选层，不验证分钟级尾盘结构。",
            "- 将来的冻结集必须移除同日全日换手率、同日推算流通股本、不安全原始退出价及所有未来标签；当前没有获准的冻结集。",
            "- 当前 `_safe` 后缀仅表示交易日日期已对齐且聚合 VWAP 为正，不代表实际可成交；修复版应改名为 `_date_aligned` 并把可成交性保持为 `UNKNOWN`。",
            "- 当前聚合未保存涨跌停、盘口和早盘窗口精确根数，不能据此证明次日退出可执行。",
            "- 2024 年仍是工程和样本量门禁，不用于参数定稿。",
            "- 当精确字段存在时，14:30 完整性逐一检查 42 个预期时间戳、重复、缺失、非预期时间戳、14:30 根和源顺序；旧数据缺字段时仍保持门禁失败。",
            "- 行业字段是证监会行业分类，可用于行业分组，不等同于题材/概念热门板块。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    root = pathlib.Path(args.input).expanduser().resolve()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists() and not args.reuse_audited:
        raise SystemExit(f"输出目录已存在，拒绝覆盖：{output}")
    if args.reuse_audited and not (output / "audited_features.parquet").is_file():
        raise SystemExit("--reuse-audited 要求输出目录中已有 audited_features.parquet")

    required_paths = [
        root / "state.json",
        root / "codes.json",
        root / "universe.parquet",
        root / "industry.parquet",
    ]
    missing_paths = [str(path) for path in required_paths if not path.is_file()]
    feature_paths = sorted((root / "features").glob("part-*.parquet"))
    if not feature_paths:
        missing_paths.append(str(root / "features" / "part-*.parquet"))
    if missing_paths:
        raise SystemExit("缺少输入文件：" + "、".join(missing_paths))

    features_glob = str(root / "features" / "*.parquet")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    codes = json.loads((root / "codes.json").read_text(encoding="utf-8"))
    completed = state.get("completed_codes", [])
    unresolved = sorted(
        {item.get("code") for item in state.get("failures", []) if item.get("code")}
        - set(completed)
    )
    if not args.reuse_audited:
        output.mkdir(parents=True)
    connection = duckdb.connect()
    feature_columns = {
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [features_glob]
        ).fetchall()
    }
    asof_completeness_columns = {
        "bar_count1430",
        "distinct_bar_count1430",
        "has_1430_bar",
        "missing_expected_bar_count1430",
        "duplicate_bar_count1430",
        "unexpected_bar_count1430",
        "source_out_of_order_count1430",
        "exact_1430_complete",
    }
    missing_asof_completeness_columns = sorted(
        asof_completeness_columns - feature_columns
    )

    incomplete_intraday_condition = (
        "NOT coalesce(exact_1430_complete,false)"
        if "exact_1430_complete" in feature_columns
        else (
            "bar_count<>48 OR first_bar_time<>'0935' "
            "OR last_bar_time<>'1500' OR strength_5m_count<>37"
        )
    )
    basic = row_dict(
        connection,
        f"""
        SELECT count(*) AS row_count,count(DISTINCT code) AS feature_codes,
          count(DISTINCT date) AS trading_dates,
          count(*)-count(DISTINCT code||'|'||date) AS duplicate_rows,
          count(*) FILTER(WHERE {incomplete_intraday_condition})
            AS incomplete_intraday_rows,
          count(*) FILTER(WHERE trade_status<>1) AS nontrade_status_rows,
          count(*) FILTER(WHERE is_st) AS st_rows,
          count(*) FILTER(WHERE listing_days_prior<60) AS young_rows,
          count(*) FILTER(WHERE price1430 IS NULL OR NOT isfinite(price1430)
            OR price1430<=0 OR cum_volume1430<=0 OR cum_amount1430<=0
            OR vwap1430<=0) AS invalid_intraday_values,
          min(date) AS min_date,max(date) AS max_date
        FROM read_parquet(?)
        """,
        [features_glob],
    )
    basic.update(
        {
            "total_codes": len(codes),
            "completed_codes": len(set(completed)),
            "remaining_codes": len(set(codes) - set(completed)),
            "failure_attempts": len(state.get("failures", [])),
            "unresolved_failures": len(unresolved),
            "completed_without_feature_rows": len(set(completed))
            - basic["feature_codes"],
            "missing_asof_completeness_columns": missing_asof_completeness_columns,
            "intraday_completeness_basis": (
                "截至14:30的42根精确时间戳完整性"
                if "exact_1430_complete" in feature_columns
                else "全天48根代理完整性"
            ),
        }
    )
    state_parts = state.get("parts", [])
    state_part_rows_by_path = {
        str(pathlib.Path(item["path"]).expanduser().resolve()): int(item.get("rows", -1))
        for item in state_parts
        if item.get("path")
    }
    actual_part_rows_by_path = {
        str(pathlib.Path(filename).resolve()): row_count
        for filename, row_count in connection.execute(
            """
            SELECT filename,count(*)
            FROM read_parquet(?,filename=true)
            GROUP BY filename
            """,
            [features_glob],
        ).fetchall()
    }
    all_part_paths = set(state_part_rows_by_path) | set(actual_part_rows_by_path)
    basic.update(
        {
            "state_part_count": len(state_parts),
            "actual_part_count": len(feature_paths),
            "duplicate_state_part_paths": len(state_parts)
            - len(state_part_rows_by_path),
            "part_path_mismatches": len(
                set(state_part_rows_by_path) ^ set(actual_part_rows_by_path)
            ),
            "part_row_mismatches": sum(
                state_part_rows_by_path.get(path)
                != actual_part_rows_by_path.get(path)
                for path in all_part_paths
            ),
            "state_part_rows": sum(
                int(item.get("rows", 0)) for item in state_parts
            ),
        }
    )

    industry_metrics = row_dict(
        connection,
        """
        WITH ind AS (
          SELECT snapshot_date,update_date,code,industry FROM read_parquet(?)
        ), mapped AS (
          SELECT f.code,f.date,i.industry,i.snapshot_date,i.update_date
          FROM read_parquet(?) f
          ASOF LEFT JOIN ind i ON f.code=i.code AND f.date>=i.snapshot_date
        )
        SELECT count(*) FILTER(WHERE industry IS NULL OR trim(industry)='')
                 AS missing_industry_rows,
               count(*) FILTER(WHERE snapshot_date>date) AS future_industry_rows,
               count(*) FILTER(WHERE coalesce(update_date,'')<>''
                 AND update_date>date) AS future_industry_update_rows
        FROM mapped
        """,
        [str(root / "industry.parquet"), features_glob],
    )
    basic.update(industry_metrics)

    next_metrics = row_dict(
        connection,
        """
        WITH market_dates AS (
          SELECT date,lead(date) OVER(ORDER BY date) AS next_market_date
          FROM (SELECT DISTINCT date FROM read_parquet(?) UNION SELECT '2025-01-02')
        ), x AS (
          SELECT f.*,m.next_market_date FROM read_parquet(?) f JOIN market_dates m USING(date)
        )
        SELECT count(*) FILTER(WHERE coalesce(next_date,'')='') AS missing_next_rows,
               count(*) FILTER(WHERE coalesce(next_date,'')<>''
                 AND next_date<>next_market_date) AS delayed_next_rows,
               count(*) FILTER(WHERE next_date=next_market_date AND
                 (next_exit_first_5m_vwap IS NULL OR NOT isfinite(next_exit_first_5m_vwap)
                  OR next_exit_first_5m_vwap<=0)) AS exact_next_bad_first_rows,
               count(*) FILTER(WHERE next_date=next_market_date AND
                 (next_exit_to_1000_vwap IS NULL OR NOT isfinite(next_exit_to_1000_vwap)
                  OR next_exit_to_1000_vwap<=0)) AS exact_next_bad_1000_rows
        FROM x
        """,
        [features_glob, features_glob],
    )
    basic.update(next_metrics)

    audited_path = output / "audited_features.parquet"
    if not args.reuse_audited:
        create_audited_dataset(connection, root, audited_path)
    audited = row_dict(
        connection,
        """
        WITH base AS (
          SELECT *,
            raw_same_day_float_shares_inferred*raw_full_day_turnover/100.0
              AS reconstructed_daily_volume
          FROM read_parquet(?)
        ), dates AS (
          SELECT date,row_number() OVER(ORDER BY date) AS date_index
          FROM (SELECT DISTINCT date FROM base)
        ), codes AS (
          SELECT DISTINCT code FROM base
        ), panel_base AS (
          SELECT c.code,d.date,d.date_index,b.trade_status
          FROM codes c CROSS JOIN dates d
          LEFT JOIN base b USING(code,date)
        ), panel AS (
          SELECT *,
            count(*) OVER (
              PARTITION BY code ORDER BY date
              ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) AS observed_prev5_dates,
            count(*) OVER (
              PARTITION BY code ORDER BY date
              ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
            ) AS observed_prev20_dates,
            count(*) OVER (
              PARTITION BY code ORDER BY date
              ROWS BETWEEN 122 PRECEDING AND 1 PRECEDING
            ) AS observed_prev122_dates,
            count(*) FILTER(WHERE coalesce(trade_status,0)<>1) OVER (
              PARTITION BY code ORDER BY date
              ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) AS invalid_prev5_visible,
            count(*) FILTER(WHERE coalesce(trade_status,0)<>1) OVER (
              PARTITION BY code ORDER BY date
              ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
            ) AS invalid_prev20_visible,
            count(*) FILTER(WHERE coalesce(trade_status,0)<>1) OVER (
              PARTITION BY code ORDER BY date
              ROWS BETWEEN 122 PRECEDING AND 1 PRECEDING
            ) AS invalid_prev122_visible,
            lag(trade_status) OVER (PARTITION BY code ORDER BY date)
              AS prior_market_session_trade_status
          FROM panel_base
        ), w AS (
          SELECT b.*,p.date_index,p.observed_prev5_dates,p.observed_prev20_dates,
                 p.observed_prev122_dates,p.invalid_prev5_visible,
                 p.invalid_prev20_visible,p.invalid_prev122_visible,
                 p.prior_market_session_trade_status
          FROM base b JOIN panel p USING(code,date)
        )
        SELECT count(*) AS audited_rows,
          count(*)-count(DISTINCT code||'|'||date) AS audited_duplicate_rows,
          count(*) FILTER(WHERE strategy_universe_eligible) AS eligible_rows,
          count(*) FILTER(WHERE outcome_status='AVAILABLE') AS outcome_available_rows,
          count(*) FILTER(WHERE outcome_status='NEXT_SESSION_UNTRADABLE')
            AS next_session_untradable_rows,
          count(*) FILTER(WHERE outcome_status='NEXT_SESSION_MISSING')
            AS next_session_missing_rows,
          count(*) FILTER(WHERE strategy_universe_eligible AND NOT outcome_first_available)
            AS eligible_without_first_exit_rows,
          count(*) FILTER(WHERE strategy_universe_eligible AND NOT outcome_1000_available)
            AS eligible_without_1000_exit_rows,
          count(*) FILTER(WHERE strategy_universe_eligible AND
            (turnover1430_asof IS NULL OR NOT isfinite(turnover1430_asof)
             OR turnover1430_asof<=0)) AS eligible_bad_turnover_rows,
          count(*) FILTER(WHERE strategy_universe_eligible AND
            (float_shares_asof_date IS NULL OR float_shares_asof_date>=date))
              AS eligible_nonhistorical_shares_rows,
          count(*) FILTER(WHERE strategy_universe_eligible AND
            abs(turnover1430_asof-cum_volume1430/float_shares_asof*100.0)>1e-10)
              AS eligible_turnover_formula_errors,
          count(*) FILTER(WHERE strategy_universe_eligible AND
            (NOT intraday_complete OR NOT current_tradeable
             OR NOT feature_values_valid OR NOT history_complete
             OR NOT industry_valid OR is_st OR listing_days_prior<60))
              AS eligible_rule_violations,
          count(*) FILTER(WHERE coalesce(next_date,'')<>''
            AND next_date<>next_market_date
            AND (outcome_status<>'NEXT_SESSION_UNTRADABLE'
              OR next_exit_first_5m_vwap_safe IS NOT NULL
              OR next_exit_to_1000_vwap_safe IS NOT NULL))
              AS delayed_quarantine_errors,
          count(*) FILTER(WHERE coalesce(next_date,'')=''
            AND (outcome_status<>'NEXT_SESSION_MISSING'
              OR next_exit_first_5m_vwap_safe IS NOT NULL
              OR next_exit_to_1000_vwap_safe IS NOT NULL))
              AS missing_quarantine_errors,
          count(*) FILTER(WHERE next_date=next_market_date AND
            ((outcome_first_available AND
                next_exit_first_5m_vwap_safe IS DISTINCT FROM raw_next_exit_first_5m_vwap)
             OR (NOT outcome_first_available AND
                next_exit_first_5m_vwap_safe IS NOT NULL)))
              AS first_exit_safety_errors,
          count(*) FILTER(WHERE next_date=next_market_date AND
            ((outcome_1000_available AND
                next_exit_to_1000_vwap_safe IS DISTINCT FROM raw_next_exit_to_1000_vwap)
             OR (NOT outcome_1000_available AND
                next_exit_to_1000_vwap_safe IS NOT NULL)))
              AS exit_1000_safety_errors,
          count(*) FILTER(WHERE cum_volume1430>reconstructed_daily_volume+1)
              AS minute_daily_volume_upper_bound_rows,
          count(*) FILTER(WHERE strategy_universe_eligible
            AND cum_volume1430>reconstructed_daily_volume+1)
              AS eligible_minute_daily_volume_upper_bound_rows,
          count(*) FILTER(WHERE strategy_universe_eligible
            AND observed_prev5_dates=5 AND invalid_prev5_visible>0)
              AS eligible_suspended_prev5_rows,
          count(*) FILTER(WHERE strategy_universe_eligible
            AND observed_prev20_dates=20 AND invalid_prev20_visible>0)
              AS eligible_suspended_prev20_rows,
          count(*) FILTER(WHERE strategy_universe_eligible
            AND observed_prev122_dates=122 AND invalid_prev122_visible>0)
              AS eligible_suspended_prev122_rows,
          count(*) FILTER(WHERE strategy_universe_eligible
            AND observed_prev5_dates<5) AS eligible_prev5_unverifiable_rows,
          count(*) FILTER(WHERE strategy_universe_eligible
            AND observed_prev20_dates<20) AS eligible_prev20_unverifiable_rows,
          count(*) FILTER(WHERE strategy_universe_eligible
            AND observed_prev122_dates<122) AS eligible_prev122_unverifiable_rows,
          count(*) FILTER(WHERE strategy_universe_eligible AND trade_status=1
            AND date_index>1 AND coalesce(prior_market_session_trade_status,0)<>1)
              AS eligible_visible_resume_rows
        FROM w
        """,
        [str(audited_path)],
    )

    cross_source = crosscheck_tencent(connection, features_glob)
    fingerprint, source_file_count, source_bytes = source_fingerprint(root)
    gates = [
        {
            "name": "采集完成",
            "status": "PASS" if basic["remaining_codes"] == 0 and not unresolved else "FAIL",
            "evidence": (
                f"状态完成 {basic['completed_codes']}/{basic['total_codes']}，"
                f"实际有观测 {basic['feature_codes']}，全期无记录 "
                f"{basic['completed_without_feature_rows']}，未解决失败 {len(unresolved)}"
            ),
        },
        {
            "name": "分片清单与行数对账",
            "status": "PASS"
            if basic["state_part_count"] == basic["actual_part_count"]
            and basic["duplicate_state_part_paths"] == 0
            and basic["part_path_mismatches"] == 0
            and basic["part_row_mismatches"] == 0
            and basic["state_part_rows"] == basic["row_count"]
            else "FAIL",
            "evidence": (
                f"state/实际分片 {basic['state_part_count']}/"
                f"{basic['actual_part_count']}，路径差异 {basic['part_path_mismatches']}，"
                f"state重复路径 {basic['duplicate_state_part_paths']}，"
                f"行数差异分片 {basic['part_row_mismatches']}，"
                f"state/实际行 {basic['state_part_rows']}/{basic['row_count']}"
            ),
        },
        {
            "name": "2024 交易日覆盖",
            "status": "PASS"
            if basic["trading_dates"] == 242
            and basic["min_date"] == "2024-01-02"
            and basic["max_date"] == "2024-12-31"
            else "FAIL",
            "evidence": (
                f"{basic['min_date']}..{basic['max_date']}，"
                f"交易日 {basic['trading_dates']}"
            ),
        },
        {
            "name": "原始股票日唯一性",
            "status": "PASS" if basic["duplicate_rows"] == 0 else "FAIL",
            "evidence": f"重复股票日 {basic['duplicate_rows']}",
        },
        {
            "name": "审计集行数与唯一性",
            "status": "PASS"
            if audited["audited_rows"] == basic["row_count"]
            and audited["audited_duplicate_rows"] == 0
            else "FAIL",
            "evidence": (
                f"原始/审计 {basic['row_count']}/{audited['audited_rows']}，"
                f"审计重复 {audited['audited_duplicate_rows']}"
            ),
        },
        {
            "name": "截至 14:30 的分钟完整性证据",
            "status": "PASS" if not missing_asof_completeness_columns else "FAIL",
            "evidence": (
                "缺少聚合字段 " + ", ".join(missing_asof_completeness_columns)
                if missing_asof_completeness_columns
                else "14:30 根数、关键时点、缺失与重复字段齐全"
            ),
        },
        {
            "name": "历史行业时点",
            "status": "PASS"
            if basic["future_industry_rows"] == 0
            and basic["future_industry_update_rows"] == 0
            else "FAIL",
            "evidence": (
                f"未来快照/行业更新时间映射 {basic['future_industry_rows']}/"
                f"{basic['future_industry_update_rows']}"
            ),
        },
        {
            "name": "上一历史行股本机械时点检查",
            "status": "PASS"
            if audited["eligible_bad_turnover_rows"] == 0
            and audited["eligible_nonhistorical_shares_rows"] == 0
            and audited["eligible_turnover_formula_errors"] == 0
            else "FAIL",
            "evidence": (
                "异常值/非历史行股本/公式误差 "
                f"{audited['eligible_bad_turnover_rows']}/"
                f"{audited['eligible_nonhistorical_shares_rows']}/"
                f"{audited['eligible_turnover_formula_errors']}"
            ),
        },
        {
            "name": "5 分钟量与日线全日量一致性",
            "status": "PASS"
            if audited["minute_daily_volume_upper_bound_rows"] == 0
            else "FAIL",
            "evidence": (
                "14:30 累计量已超过日线全日量 "
                f"{audited['minute_daily_volume_upper_bound_rows']} 条，"
                "其中基础可用集 "
                f"{audited['eligible_minute_daily_volume_upper_bound_rows']} 条"
            ),
        },
        {
            "name": "停牌历史窗口与复牌日",
            "status": "PASS"
            if audited["eligible_suspended_prev5_rows"] == 0
            and audited["eligible_suspended_prev20_rows"] == 0
            and audited["eligible_suspended_prev122_rows"] == 0
            and audited["eligible_prev5_unverifiable_rows"] == 0
            and audited["eligible_prev20_unverifiable_rows"] == 0
            and audited["eligible_prev122_unverifiable_rows"] == 0
            and audited["eligible_visible_resume_rows"] == 0
            else "FAIL",
            "evidence": (
                "基础可用集中前5/20/122行可见停牌污染 "
                f"{audited['eligible_suspended_prev5_rows']}/"
                f"{audited['eligible_suspended_prev20_rows']}/"
                f"{audited['eligible_suspended_prev122_rows']}，"
                "跨 2023 未落盘回看期 5/20/122日 "
                f"{audited['eligible_prev5_unverifiable_rows']}/"
                f"{audited['eligible_prev20_unverifiable_rows']}/"
                f"{audited['eligible_prev122_unverifiable_rows']}，"
                f"可见复牌日 {audited['eligible_visible_resume_rows']}"
            ),
        },
        {
            "name": "基础异常样本隔离",
            "status": "PASS" if audited["eligible_rule_violations"] == 0 else "FAIL",
            "evidence": f"基础可用集规则冲突 {audited['eligible_rule_violations']}",
        },
        {
            "name": "次日跳日与缺失隔离",
            "status": "PASS"
            if audited["delayed_quarantine_errors"] == 0
            and audited["missing_quarantine_errors"] == 0
            else "FAIL",
            "evidence": (
                f"跳过下一市场日/缺失 {basic['delayed_next_rows']}/{basic['missing_next_rows']}，"
                "隔离错误 "
                f"{audited['delayed_quarantine_errors']}/"
                f"{audited['missing_quarantine_errors']}"
            ),
        },
        {
            "name": "次日日期对齐价格映射",
            "status": "PASS"
            if audited["first_exit_safety_errors"] == 0
            and audited["exit_1000_safety_errors"] == 0
            else "FAIL",
            "evidence": (
                "首窗/10:00 日期对齐字段错误 "
                f"{audited['first_exit_safety_errors']}/"
                f"{audited['exit_1000_safety_errors']}"
            ),
        },
        {
            "name": "第二来源日线抽样",
            "status": "PASS"
            if cross_source["matched_stock_days"] > 0
            and all(cross_source["matched_stock_days_by_code"].values())
            and cross_source["price_range_mismatches"] == 0
            and cross_source["preclose_unexplained_mismatches"] == 0
            and cross_source["volume_mismatches_over_0_5pct"] == 0
            and not cross_source["errors"]
            else "FAIL",
            "evidence": (
                f"匹配 {cross_source['matched_stock_days']}，价格/未解释前收/成交量异常 "
                f"{cross_source['price_range_mismatches']}/"
                f"{cross_source['preclose_unexplained_mismatches']}/"
                f"{cross_source['volume_mismatches_over_0_5pct']}；"
                f"除权除息解释 {cross_source['preclose_corporate_action_rows']}"
            ),
        },
    ]
    hard_gate_passed = all(item["status"] != "FAIL" for item in gates)
    status = "PASS_WITH_CORRECTIONS" if hard_gate_passed else "BLOCKED_DATA"
    eligible_path = output / "eligible_features.parquet"
    if hard_gate_passed:
        connection.execute(
            f"""COPY (
                  SELECT
                    code,date,price1430,cum_volume1430,cum_amount1430,vwap1430,
                    strength_5m_count,above_vwap_5m_count,above_vwap_5m_ratio,
                    preclose,prev5_volume,recent20_complete,recent_strong,
                    volume3_complete,volume3_ok,listing_days_prior,
                    trade_status,is_st,ret1430,volume_ratio1430,
                    float_shares_asof,float_shares_asof_date,turnover1430_asof,
                    industry_snapshot_date,industry_update_date,
                    industry,classification,current_tradeable,
                    feature_values_valid,history_complete,industry_valid,
                    strategy_universe_eligible
                  FROM read_parquet('{sql_path(audited_path)}')
                  WHERE strategy_universe_eligible
                ) TO '{sql_path(eligible_path)}'
                (FORMAT PARQUET, COMPRESSION ZSTD)"""
        )
    report = {
        "version": "YYX-OH-2024-DATA-GATE-V1",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "source": {
            "root": str(root),
            "sha256": fingerprint,
            "file_count": source_file_count,
            "bytes": source_bytes,
        },
        "basic": basic,
        "audited": audited,
        "cross_source": cross_source,
        "gates": gates,
        "frozen_dataset_generated": hard_gate_passed,
        "outputs": {
            "audited_features": str(audited_path),
            "eligible_features": str(eligible_path) if hard_gate_passed else None,
        },
    }
    (output / "quality-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output / "quality-report.md").write_text(markdown_report(report), encoding="utf-8")
    print("RESULT=" + json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
