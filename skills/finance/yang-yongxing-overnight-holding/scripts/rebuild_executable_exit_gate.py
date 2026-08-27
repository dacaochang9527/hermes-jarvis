#!/usr/bin/env python3
"""核验次日 9:35—10:00 的 5 分钟级退出可成交性并冻结工程数据集。

本脚本只确认 5 分钟 K 线模型能够观察到真实成交、关键时点完整，并正确隔离
停牌、跌停锁死和上游量能冲突。它不声称还原逐笔排队或任意资金规模的成交。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import pathlib
import time
import urllib.parse
import urllib.request

import duckdb


TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
DAILY_SOURCE_MAX_RELATIVE_ERROR = 0.005
PRICE_EPSILON = 0.0005
DAILY_RANGE_TOLERANCE = 0.011


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audited-input", required=True)
    parser.add_argument("--completeness", required=True)
    parser.add_argument("--supplement", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cross-source-samples", type=int, default=30)
    return parser.parse_args()


def sql_path(path: pathlib.Path) -> str:
    return str(path).replace("'", "''")


def fingerprint(path: pathlib.Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest(), size


def row_dict(connection: duckdb.DuckDBPyConnection, query: str, params=None) -> dict:
    cursor = connection.execute(query, params or [])
    row = cursor.fetchone()
    return dict(zip([item[0] for item in cursor.description], row))


def fetch_tencent_daily(code: str, date: str) -> dict:
    symbol = code.replace(".", "")
    params = {"param": f"{symbol},day,{date},{date},10,bfq"}
    request = urllib.request.Request(
        TENCENT_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://stock.qq.com/"},
    )
    last_error = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = (payload.get("data", {}).get(symbol, {}) or {}).get("day") or []
            if not rows:
                raise RuntimeError("未返回日线")
            raw = rows[0]
            return {
                "date": raw[0],
                "open": float(raw[1]),
                "close": float(raw[2]),
                "high": float(raw[3]),
                "low": float(raw[4]),
                "volume": float(raw[5]) * 100.0,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(last_error)


def crosscheck_boundary_daily(
    connection: duckdb.DuckDBPyConnection,
    supplement_glob: str,
    sample_size: int,
) -> dict:
    cursor = connection.execute(
        """
        SELECT code,date,daily_open,daily_high,daily_low,daily_close,daily_volume
        FROM read_parquet(?,union_by_name=true)
        WHERE date='2025-01-02' AND daily_row_present AND daily_trade_status=1
          AND isfinite(daily_volume) AND daily_volume>0
        ORDER BY md5('YYX-OH-EXIT-2025-01-02|'||code)
        LIMIT ?
        """,
        [supplement_glob, sample_size],
    )
    columns = [item[0] for item in cursor.description]
    samples = [dict(zip(columns, row)) for row in cursor.fetchall()]
    evidence: list[dict] = []
    errors: list[dict] = []
    for sample in samples:
        try:
            remote = fetch_tencent_daily(sample["code"], sample["date"])
            volume_error = abs(remote["volume"] - sample["daily_volume"]) / max(
                sample["daily_volume"], 1.0
            )
            price_errors = {
                field: abs(remote[field] - sample[f"daily_{field}"])
                for field in ("open", "high", "low", "close")
            }
            evidence.append(
                {
                    "code": sample["code"],
                    "date": sample["date"],
                    "volume_relative_error": volume_error,
                    "price_absolute_errors": price_errors,
                    "pass": volume_error <= DAILY_SOURCE_MAX_RELATIVE_ERROR
                    and max(price_errors.values()) <= DAILY_RANGE_TOLERANCE,
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "code": sample["code"],
                    "date": sample["date"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    passed = sum(item["pass"] for item in evidence)
    return {
        "source": "Tencent unadjusted daily kline",
        "target_date": "2025-01-02",
        "selected_samples": len(samples),
        "matched_samples": len(evidence),
        "passed_samples": passed,
        "failed_samples": len(evidence) - passed,
        "errors": errors,
        "samples": evidence,
    }


def status_counts(
    connection: duckdb.DuckDBPyConnection, path: pathlib.Path, column: str
) -> dict[str, int]:
    return {
        status: count
        for status, count in connection.execute(
            f"SELECT {column},count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
            [str(path)],
        ).fetchall()
    }


def markdown_report(report: dict) -> str:
    metrics = report["metrics"]
    cross = report["boundary_cross_source"]
    first = report["first_5m_status_counts"]
    window = report["to_1000_status_counts"]
    lines = [
        "# 2024 年次日退出可成交性数据门禁报告",
        "",
        f"- 门禁状态：**{report['status']}**",
        f"- 2024工程数据状态：**{report['overall_quality_status']}**",
        f"- 生成时间：{report['created_at']}",
        f"- 输入指纹：`{report['source']['sha256']}`",
        "",
        "## 结论",
        "",
        "- 次日日期对齐、停牌、09:35—10:00关键5分钟、涨跌停价和成交价格已逐股票日分类。",
        "- 跌停锁死和停牌是有效尾部结果，不会从样本中静默删除；关键分钟缺失或上游5分钟量冲突则明确隔离。",
        "- `EXECUTABLE_5M_BAR_MODEL` 只表示窗口内存在高于跌停价的真实成交，可用于冻结的5分钟成交模型；不等于任意仓位均可成交。",
        "- 逐笔排队、盘口深度、第一分钟VWAP和条件退出仍须1分钟/逐笔数据验证。",
        "",
        "## 全量统计",
        "",
        f"- 输入股票日：{metrics['row_count']:,}；源特征门禁通过：{metrics['source_feature_gate_rows']:,}。",
        f"- 补采目标/已完成/重复：{metrics['supplement_target_rows']:,}/{metrics['supplement_rows']:,}/{metrics['supplement_duplicate_rows']:,}。",
        f"- 次日日期对齐错误：{metrics['next_date_alignment_error_rows']:,}。",
        f"- 未完成可成交性分类：{metrics['unresolved_executability_rows']:,}。",
        f"- 关键窗口不完整：{metrics['key_window_incomplete_rows']:,}。",
        f"- 次日上游5分钟量冲突隔离：{metrics['exit_volume_conflict_rows']:,}。",
        f"- 5%/10%涨跌停参考价异常隔离：{metrics['limit_reference_conflict_rows']:,}。",
        f"- 09:35模型可成交：{metrics['first_5m_executable_rows']:,}；跌停锁死：{metrics['first_5m_locked_rows']:,}。",
        f"- 10:00窗口模型可成交：{metrics['to_1000_executable_rows']:,}；跌停锁死：{metrics['to_1000_locked_rows']:,}。",
        f"- 冻结信号时点特征：{metrics['eligible_feature_rows']:,}；退出结果：{metrics['exit_outcome_rows']:,}。",
        "",
        "## 09:35 状态分布",
        "",
    ]
    lines.extend(f"- `{key}`：{value:,}" for key, value in first.items())
    lines.extend(["", "## 10:00 窗口状态分布", ""])
    lines.extend(f"- `{key}`：{value:,}" for key, value in window.items())
    lines.extend(
        [
            "",
            "## 年度边界第二来源核验",
            "",
            f"- 2025-01-02抽样/匹配/通过：{cross['selected_samples']}/{cross['matched_samples']}/{cross['passed_samples']}。",
            f"- 价格或成交量不一致：{cross['failed_samples']}；接口错误：{len(cross['errors'])}。",
            "",
            "## 冻结产物边界",
            "",
            "- `eligible_features.parquet` 仅保存14:30当时可见或此前已知的字段，不含次日价格、同日收盘字段和原始未来标签。",
            "- `exit_outcomes.parquet` 与信号时点特征物理分离；未来回放必须按 `code,date` 显式连接。",
            "- 无法退出、跌停锁死和数据隔离行均保留在退出结果中，不得为提高收益表现而删除。",
            "- 2024年只通过工程与样本量门禁，不用于回测、调参或参数定稿；完整V1仍需多年市场阶段数据和1分钟层验证。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    audited_input = pathlib.Path(args.audited_input).expanduser().resolve()
    completeness = pathlib.Path(args.completeness).expanduser().resolve()
    supplement = pathlib.Path(args.supplement).expanduser().resolve()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"输出目录已存在，拒绝覆盖：{output}")
    if not audited_input.is_file():
        raise SystemExit(f"输入不存在：{audited_input}")
    if not completeness.is_dir():
        raise SystemExit(f"完整性目录不存在：{completeness}")
    if not supplement.is_dir():
        raise SystemExit(f"退出补采目录不存在：{supplement}")
    state_path = supplement.parent / "state.json"
    targets_path = supplement.parent / "targets.json"
    if not state_path.is_file() or not targets_path.is_file():
        raise SystemExit("退出补采缺少 state.json 或 targets.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    targets = json.loads(targets_path.read_text(encoding="utf-8"))
    if len(state.get("completed_targets", [])) != len(targets) or state.get("failures"):
        raise SystemExit("退出补采尚未完成或仍有失败，拒绝生成门禁")

    connection = duckdb.connect()
    supplement_glob = str(supplement / "*.parquet")
    boundary_cross = crosscheck_boundary_daily(
        connection, supplement_glob, args.cross_source_samples
    )
    boundary_cross_pass = (
        boundary_cross["matched_samples"] >= 20
        and boundary_cross["failed_samples"] == 0
    )

    output.mkdir(parents=True)
    normalized_supplement = output / "normalized_exit_supplement.parquet"
    connection.execute(
        f"""
        COPY (
          SELECT * FROM read_parquet('{sql_path(pathlib.Path(supplement_glob))}',
                                     union_by_name=true)
          ORDER BY code,date
        ) TO '{sql_path(normalized_supplement)}'
          (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )

    audited_destination = output / "audited_with_exit_executability.parquet"
    a = sql_path(audited_input)
    c = sql_path(completeness / "*.parquet")
    s = sql_path(normalized_supplement)
    d = sql_path(audited_destination)
    connection.execute(
        f"""
        COPY (
          WITH next_rows AS (
            SELECT code,date,preclose,trade_status,is_st,low_bfq,high_bfq,
              intraday_volume_consistency_pass
            FROM read_parquet('{a}')
          ), joined AS (
            SELECT a.*,
              n.preclose AS existing_exit_preclose,
              n.trade_status AS existing_exit_trade_status,
              n.is_st AS existing_exit_is_st,
              n.low_bfq AS existing_exit_daily_low,
              n.high_bfq AS existing_exit_daily_high,
              n.intraday_volume_consistency_pass
                AS existing_exit_volume_consistency_pass,
              coalesce(
                c.bar_count=48 AND c.distinct_bar_count=48
                AND c.duplicate_bar_count=0 AND c.unexpected_bar_count=0
                AND c.missing_expected_bar_count=0
                AND c.source_out_of_order_count=0,false
              ) AS existing_exit_window_complete,
              s.code IS NOT NULL AS exit_supplement_present,
              s.daily_row_present AS sup_daily_row_present,
              s.daily_preclose AS sup_daily_preclose,
              s.daily_trade_status AS sup_daily_trade_status,
              s.daily_is_st AS sup_daily_is_st,
              s.daily_low AS sup_daily_low,
              s.daily_high AS sup_daily_high,
              s.exact_exit_window_complete
                AS sup_exact_exit_window_complete,
              s.first_5m_vwap AS sup_first_5m_vwap,
              s.first_5m_high AS sup_first_5m_high,
              s.to_1000_vwap AS sup_to_1000_vwap,
              s.to_1000_high AS sup_to_1000_high,
              s.minute_exceeds_daily_volume
                AS sup_minute_exceeds_daily_volume
            FROM read_parquet('{a}') a
            LEFT JOIN next_rows n
              ON n.code=a.code AND n.date=a.next_market_date
            LEFT JOIN read_parquet('{c}') c
              ON c.code=a.code AND c.date=a.next_market_date
            LEFT JOIN read_parquet('{s}') s
              ON s.code=a.code AND s.date=a.next_market_date
          ), resolved AS (
            SELECT *,
              coalesce(sup_daily_preclose,existing_exit_preclose)
                AS exit_preclose,
              coalesce(sup_daily_trade_status,existing_exit_trade_status,0)
                AS exit_trade_status,
              coalesce(sup_daily_is_st,existing_exit_is_st,false) AS exit_is_st,
              coalesce(sup_daily_low,existing_exit_daily_low) AS exit_daily_low,
              coalesce(sup_daily_high,existing_exit_daily_high) AS exit_daily_high,
              CASE WHEN exit_supplement_present
                   THEN sup_exact_exit_window_complete
                   ELSE existing_exit_window_complete END
                AS exit_key_window_complete,
              CASE WHEN exit_supplement_present THEN sup_first_5m_vwap
                   ELSE raw_next_exit_first_5m_vwap END
                AS exit_first_5m_vwap_resolved,
              CASE WHEN exit_supplement_present THEN sup_to_1000_vwap
                   ELSE raw_next_exit_to_1000_vwap END
                AS exit_to_1000_vwap_resolved,
              CASE WHEN exit_supplement_present THEN sup_first_5m_high END
                AS exit_first_5m_high_observed,
              CASE WHEN exit_supplement_present THEN sup_to_1000_high END
                AS exit_to_1000_high_observed,
              CASE
                WHEN existing_exit_volume_consistency_pass IS NOT NULL
                  THEN existing_exit_volume_consistency_pass
                WHEN exit_supplement_present AND sup_daily_row_present
                  AND sup_daily_trade_status=1
                  AND sup_exact_exit_window_complete
                  THEN NOT sup_minute_exceeds_daily_volume
                ELSE NULL
              END AS exit_minute_volume_consistency_pass,
              CASE
                WHEN existing_exit_volume_consistency_pass IS NOT NULL
                  THEN '2024_DUAL_DAILY_SOURCE_GATE'
                WHEN exit_supplement_present AND date='2024-12-31'
                  THEN '2025_BOUNDARY_BAOSTOCK_DAILY_BOUND_WITH_TENCENT_SAMPLE'
                ELSE 'UNAVAILABLE'
              END AS exit_volume_consistency_source
            FROM joined
          ), limits AS (
            SELECT *,
              CASE WHEN isfinite(exit_preclose) AND exit_preclose>0
                   THEN floor(exit_preclose*
                     (CASE WHEN exit_is_st THEN 0.95 ELSE 0.90 END)*100.0+0.5)
                     /100.0 END AS exit_lower_limit,
              CASE WHEN isfinite(exit_preclose) AND exit_preclose>0
                   THEN floor(exit_preclose*
                     (CASE WHEN exit_is_st THEN 1.05 ELSE 1.10 END)*100.0+0.5)
                     /100.0 END AS exit_upper_limit
            FROM resolved
          ), statuses AS (
            SELECT *,
              CASE
                WHEN next_market_date IS NULL THEN 'NEXT_SESSION_MISSING'
                WHEN next_date<>next_market_date OR exit_trade_status<>1
                  THEN 'NEXT_SESSION_SUSPENDED_UNEXECUTABLE'
                WHEN NOT exit_key_window_complete
                  THEN 'KEY_MINUTES_INCOMPLETE_QUARANTINED'
                WHEN exit_lower_limit IS NULL OR NOT isfinite(exit_daily_low)
                  OR NOT isfinite(exit_daily_high)
                  THEN 'PRICE_LIMIT_REFERENCE_MISSING_QUARANTINED'
                WHEN exit_daily_low<exit_lower_limit-{DAILY_RANGE_TOLERANCE}
                  OR exit_daily_high<exit_lower_limit-{PRICE_EPSILON}
                  THEN 'PRICE_LIMIT_REFERENCE_CONFLICT_QUARANTINED'
                WHEN exit_minute_volume_consistency_pass=false
                  THEN 'UPSTREAM_5M_VOLUME_CONFLICT_QUARANTINED'
                WHEN NOT isfinite(exit_first_5m_vwap_resolved)
                  OR exit_first_5m_vwap_resolved<=0
                  THEN 'EXIT_PRICE_MISSING_QUARANTINED'
                WHEN exit_first_5m_vwap_resolved
                    <exit_daily_low-{DAILY_RANGE_TOLERANCE}
                  OR exit_first_5m_vwap_resolved
                    >exit_daily_high+{DAILY_RANGE_TOLERANCE}
                  THEN 'EXIT_PRICE_OUT_OF_DAILY_RANGE_QUARANTINED'
                WHEN exit_first_5m_high_observed IS NOT NULL
                  AND exit_first_5m_high_observed
                    <=exit_lower_limit+{PRICE_EPSILON}
                  THEN 'LOWER_LIMIT_LOCKED_UNEXECUTABLE'
                WHEN exit_first_5m_high_observed IS NOT NULL
                  AND exit_first_5m_high_observed
                    >exit_lower_limit+{PRICE_EPSILON}
                  THEN 'EXECUTABLE_5M_BAR_MODEL'
                WHEN exit_first_5m_vwap_resolved
                    >exit_lower_limit+{PRICE_EPSILON}
                  THEN 'EXECUTABLE_5M_BAR_MODEL'
                WHEN exit_daily_high<=exit_lower_limit+{PRICE_EPSILON}
                  THEN 'LOWER_LIMIT_LOCKED_UNEXECUTABLE'
                ELSE 'LOWER_LIMIT_QUEUE_UNKNOWN'
              END AS exit_first_5m_status,
              CASE
                WHEN next_market_date IS NULL THEN 'NEXT_SESSION_MISSING'
                WHEN next_date<>next_market_date OR exit_trade_status<>1
                  THEN 'NEXT_SESSION_SUSPENDED_UNEXECUTABLE'
                WHEN NOT exit_key_window_complete
                  THEN 'KEY_MINUTES_INCOMPLETE_QUARANTINED'
                WHEN exit_lower_limit IS NULL OR NOT isfinite(exit_daily_low)
                  OR NOT isfinite(exit_daily_high)
                  THEN 'PRICE_LIMIT_REFERENCE_MISSING_QUARANTINED'
                WHEN exit_daily_low<exit_lower_limit-{DAILY_RANGE_TOLERANCE}
                  OR exit_daily_high<exit_lower_limit-{PRICE_EPSILON}
                  THEN 'PRICE_LIMIT_REFERENCE_CONFLICT_QUARANTINED'
                WHEN exit_minute_volume_consistency_pass=false
                  THEN 'UPSTREAM_5M_VOLUME_CONFLICT_QUARANTINED'
                WHEN NOT isfinite(exit_to_1000_vwap_resolved)
                  OR exit_to_1000_vwap_resolved<=0
                  THEN 'EXIT_PRICE_MISSING_QUARANTINED'
                WHEN exit_to_1000_vwap_resolved
                    <exit_daily_low-{DAILY_RANGE_TOLERANCE}
                  OR exit_to_1000_vwap_resolved
                    >exit_daily_high+{DAILY_RANGE_TOLERANCE}
                  THEN 'EXIT_PRICE_OUT_OF_DAILY_RANGE_QUARANTINED'
                WHEN exit_to_1000_high_observed IS NOT NULL
                  AND exit_to_1000_high_observed
                    <=exit_lower_limit+{PRICE_EPSILON}
                  THEN 'LOWER_LIMIT_LOCKED_UNEXECUTABLE'
                WHEN exit_to_1000_high_observed IS NOT NULL
                  AND exit_to_1000_high_observed
                    >exit_lower_limit+{PRICE_EPSILON}
                  THEN 'EXECUTABLE_5M_BAR_MODEL'
                WHEN exit_to_1000_vwap_resolved
                    >exit_lower_limit+{PRICE_EPSILON}
                  THEN 'EXECUTABLE_5M_BAR_MODEL'
                WHEN exit_daily_high<=exit_lower_limit+{PRICE_EPSILON}
                  THEN 'LOWER_LIMIT_LOCKED_UNEXECUTABLE'
                ELSE 'LOWER_LIMIT_QUEUE_UNKNOWN'
              END AS exit_to_1000_status
            FROM limits
          )
          SELECT *,
            exit_first_5m_status='EXECUTABLE_5M_BAR_MODEL'
              AS exit_first_5m_bar_model_executable,
            exit_to_1000_status='EXECUTABLE_5M_BAR_MODEL'
              AS exit_to_1000_bar_model_executable,
            exit_first_5m_status<>'LOWER_LIMIT_QUEUE_UNKNOWN'
              AND exit_to_1000_status<>'LOWER_LIMIT_QUEUE_UNKNOWN'
              AS exit_executability_classified
          FROM statuses
        ) TO '{d}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )

    metrics = row_dict(
        connection,
        """
        SELECT count(*) AS row_count,
          count(*) FILTER(WHERE history_1430_volume_float_gate_pass)
            AS source_feature_gate_rows,
          ? AS supplement_target_rows,
          (SELECT count(*) FROM read_parquet(?)) AS supplement_rows,
          (SELECT count(*)-count(DISTINCT code||'|'||date)
             FROM read_parquet(?)) AS supplement_duplicate_rows,
          count(*) FILTER(WHERE next_market_date IS NOT NULL
            AND coalesce(next_date,'')<>next_market_date
            AND exit_trade_status=1) AS next_date_alignment_error_rows,
          count(*) FILTER(WHERE NOT exit_executability_classified)
            AS unresolved_executability_rows,
          count(*) FILTER(WHERE exit_first_5m_status=
            'KEY_MINUTES_INCOMPLETE_QUARANTINED'
            OR exit_to_1000_status='KEY_MINUTES_INCOMPLETE_QUARANTINED')
            AS key_window_incomplete_rows,
          count(*) FILTER(WHERE exit_first_5m_status=
            'UPSTREAM_5M_VOLUME_CONFLICT_QUARANTINED'
            OR exit_to_1000_status='UPSTREAM_5M_VOLUME_CONFLICT_QUARANTINED')
            AS exit_volume_conflict_rows,
          count(*) FILTER(WHERE exit_first_5m_status=
            'PRICE_LIMIT_REFERENCE_CONFLICT_QUARANTINED'
            OR exit_to_1000_status=
              'PRICE_LIMIT_REFERENCE_CONFLICT_QUARANTINED')
            AS limit_reference_conflict_rows,
          count(*) FILTER(WHERE exit_first_5m_bar_model_executable)
            AS first_5m_executable_rows,
          count(*) FILTER(WHERE exit_first_5m_status=
            'LOWER_LIMIT_LOCKED_UNEXECUTABLE') AS first_5m_locked_rows,
          count(*) FILTER(WHERE exit_to_1000_bar_model_executable)
            AS to_1000_executable_rows,
          count(*) FILTER(WHERE exit_to_1000_status=
            'LOWER_LIMIT_LOCKED_UNEXECUTABLE') AS to_1000_locked_rows
        FROM read_parquet(?)
        """,
        [
            len(targets),
            str(normalized_supplement),
            str(normalized_supplement),
            str(audited_destination),
        ],
    )

    gate_pass = (
        metrics["supplement_target_rows"] == metrics["supplement_rows"]
        and metrics["supplement_duplicate_rows"] == 0
        and metrics["next_date_alignment_error_rows"] == 0
        and metrics["unresolved_executability_rows"] == 0
        and boundary_cross_pass
    )

    eligible_path = output / "eligible_features.parquet"
    outcome_path = output / "exit_outcomes.parquet"
    if gate_pass:
        connection.execute(
            f"""
            COPY (
              SELECT
                code,date,preclose,price1430,cum_volume1430,cum_amount1430,
                vwap1430,strength_5m_count,above_vwap_5m_count,
                above_vwap_5m_ratio,ret1430,volume_ratio1430,
                recent20_complete_safe,recent_strong_safe,
                volume3_complete_safe,volume3_ok_safe,
                listing_market_days_prior_safe,is_resume_day_safe,
                trade_status,is_st,industry_snapshot_date,industry,classification,
                source_out_of_order_count1430,bar_count1430,
                distinct_bar_count1430,duplicate_bar_count1430,
                unexpected_bar_count1430,missing_expected_bar_count1430,
                has_1430_bar,exact_1430_complete,
                daily_history_gate_pass,intraday_1430_gate_pass,
                intraday_volume_consistency_pass,
                historical_float_shares_effective,
                historical_float_shares_effective_date,
                historical_float_shares_change_ratio,
                historical_float_shares_source,turnover1430_effective,
                turnover1430_effective_lower,turnover1430_effective_upper,
                turnover_5_10_precision_status,
                history_1430_volume_float_gate_pass
              FROM read_parquet('{d}')
              WHERE history_1430_volume_float_gate_pass
              ORDER BY date,code
            ) TO '{sql_path(eligible_path)}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
        connection.execute(
            f"""
            COPY (
              SELECT code,date,next_market_date,next_date,
                exit_trade_status,exit_is_st,exit_preclose,
                exit_daily_low,exit_daily_high,exit_lower_limit,exit_upper_limit,
                exit_key_window_complete,exit_minute_volume_consistency_pass,
                exit_volume_consistency_source,exit_supplement_present,
                exit_first_5m_vwap_resolved,exit_to_1000_vwap_resolved,
                exit_first_5m_high_observed,exit_to_1000_high_observed,
                exit_first_5m_status,exit_to_1000_status,
                exit_first_5m_bar_model_executable,
                exit_to_1000_bar_model_executable,
                exit_executability_classified
              FROM read_parquet('{d}')
              ORDER BY date,code
            ) TO '{sql_path(outcome_path)}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
        metrics["eligible_feature_rows"] = connection.execute(
            "SELECT count(*) FROM read_parquet(?)", [str(eligible_path)]
        ).fetchone()[0]
        metrics["exit_outcome_rows"] = connection.execute(
            "SELECT count(*) FROM read_parquet(?)", [str(outcome_path)]
        ).fetchone()[0]
    else:
        metrics["eligible_feature_rows"] = 0
        metrics["exit_outcome_rows"] = 0

    source_hash, source_size = fingerprint(audited_input)
    report = {
        "status": (
            "EXECUTABLE_NEXT_DAY_EXIT_PASS"
            if gate_pass
            else "EXECUTABLE_NEXT_DAY_EXIT_FAIL"
        ),
        "overall_quality_status": (
            "PASS_2024_ENGINEERING_DATA" if gate_pass else "BLOCKED_DATA"
        ),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source": {
            "path": str(audited_input),
            "sha256": source_hash,
            "bytes": source_size,
        },
        "outputs": {
            "audited": str(audited_destination),
            "eligible_features": str(eligible_path) if gate_pass else None,
            "exit_outcomes": str(outcome_path) if gate_pass else None,
            "normalized_supplement": str(normalized_supplement),
        },
        "metrics": metrics,
        "boundary_cross_source_pass": boundary_cross_pass,
        "boundary_cross_source": boundary_cross,
        "first_5m_status_counts": status_counts(
            connection, audited_destination, "exit_first_5m_status"
        ),
        "to_1000_status_counts": status_counts(
            connection, audited_destination, "exit_to_1000_status"
        ),
        "limitations": [
            "5分钟OHLCV不能还原逐笔排队和盘口深度",
            "未冻结资金规模前不能验证成交量参与率和市场冲击",
            "第一分钟VWAP及条件退出仍需1分钟数据",
            "2024仅用于工程与样本量门禁，不用于回测或调参",
        ],
    }
    (output / "boundary-cross-source-evidence.json").write_text(
        json.dumps(boundary_cross, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "exit-executability-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "exit-executability-report.md").write_text(
        markdown_report(report), encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], **metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()
