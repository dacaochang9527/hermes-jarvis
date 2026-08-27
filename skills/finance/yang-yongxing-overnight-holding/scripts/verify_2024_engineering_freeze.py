#!/usr/bin/env python3
"""独立验证 2024 工程冻结集的集合、字段和门禁不变量。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib

import duckdb


BANNED_SIGNAL_COLUMNS = {
    "next_date",
    "next_market_date",
    "open_bfq",
    "high_bfq",
    "low_bfq",
    "close_bfq",
    "volume_shares",
    "pct_chg_bfq",
    "corporate_action_json",
    "raw_same_day_float_shares_inferred",
    "raw_full_day_turnover",
    "raw_same_day_turnover1430",
    "raw_next_exit_first_5m_vwap",
    "raw_next_exit_to_1000_vwap",
    "exact_bar_count_full",
    "exact_distinct_bar_count_full",
    "exact_duplicate_bar_count_full",
    "exact_unexpected_bar_count_full",
    "exact_missing_expected_bar_count_full",
    "source_out_of_order_count",
}
BANNED_SIGNAL_PREFIXES = ("exit_", "outcome_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-dir", required=True)
    return parser.parse_args()


def fingerprint(path: pathlib.Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest(), size


def one(connection: duckdb.DuckDBPyConnection, query: str, params=None):
    return connection.execute(query, params or []).fetchone()[0]


def main() -> None:
    args = parse_args()
    root = pathlib.Path(args.freeze_dir).expanduser().resolve()
    audited = root / "audited_with_exit_executability.parquet"
    eligible = root / "eligible_features.parquet"
    outcomes = root / "exit_outcomes.parquet"
    report_path = root / "exit-executability-report.json"
    for path in (audited, eligible, outcomes, report_path):
        if not path.is_file():
            raise SystemExit(f"缺少冻结产物：{path}")
    verification_json = root / "engineering-freeze-verification.json"
    verification_md = root / "engineering-freeze-verification.md"
    if verification_json.exists() or verification_md.exists():
        raise SystemExit("独立验证报告已存在，拒绝覆盖")

    connection = duckdb.connect()
    eligible_columns = [
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(eligible)]
        ).fetchall()
    ]
    banned_columns = sorted(
        column
        for column in eligible_columns
        if column in BANNED_SIGNAL_COLUMNS
        or column.startswith(BANNED_SIGNAL_PREFIXES)
    )

    checks = {
        "audited_unique": one(
            connection,
            "SELECT count(*)-count(DISTINCT code||'|'||date)=0 FROM read_parquet(?)",
            [str(audited)],
        ),
        "eligible_unique": one(
            connection,
            "SELECT count(*)-count(DISTINCT code||'|'||date)=0 FROM read_parquet(?)",
            [str(eligible)],
        ),
        "outcomes_unique": one(
            connection,
            "SELECT count(*)-count(DISTINCT code||'|'||date)=0 FROM read_parquet(?)",
            [str(outcomes)],
        ),
        "eligible_set_exact": one(
            connection,
            """
            WITH expected AS (
              SELECT code,date FROM read_parquet(?)
              WHERE history_1430_volume_float_gate_pass
            ), actual AS (SELECT code,date FROM read_parquet(?))
            SELECT (SELECT count(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual))=0
              AND (SELECT count(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected))=0
            """,
            [str(audited), str(eligible)],
        ),
        "outcome_set_exact": one(
            connection,
            """
            WITH expected AS (SELECT code,date FROM read_parquet(?)),
                 actual AS (SELECT code,date FROM read_parquet(?))
            SELECT (SELECT count(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual))=0
              AND (SELECT count(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected))=0
            """,
            [str(audited), str(outcomes)],
        ),
        "eligible_all_source_gates_pass": one(
            connection,
            """
            SELECT count(*) FILTER(WHERE NOT history_1430_volume_float_gate_pass
              OR NOT daily_history_gate_pass OR NOT intraday_1430_gate_pass
              OR NOT intraday_volume_consistency_pass)=0
            FROM read_parquet(?)
            """,
            [str(eligible)],
        ),
        "eligible_exact_1430_structure": one(
            connection,
            """
            SELECT count(*) FILTER(WHERE NOT exact_1430_complete
              OR bar_count1430<>42 OR distinct_bar_count1430<>42
              OR duplicate_bar_count1430<>0 OR unexpected_bar_count1430<>0
              OR missing_expected_bar_count1430<>0 OR NOT has_1430_bar
              OR source_out_of_order_count1430<>0)=0
            FROM read_parquet(?)
            """,
            [str(eligible)],
        ),
        "turnover_formula_exact": one(
            connection,
            """
            SELECT count(*) FILTER(WHERE abs(turnover1430_effective-
              cum_volume1430/historical_float_shares_effective*100.0)>1e-10)=0
            FROM read_parquet(?)
            """,
            [str(eligible)],
        ),
        "outcomes_all_classified": one(
            connection,
            "SELECT count(*) FILTER(WHERE NOT exit_executability_classified)=0 FROM read_parquet(?)",
            [str(outcomes)],
        ),
        "no_limit_queue_unknown": one(
            connection,
            """
            SELECT count(*) FILTER(WHERE exit_first_5m_status='LOWER_LIMIT_QUEUE_UNKNOWN'
              OR exit_to_1000_status='LOWER_LIMIT_QUEUE_UNKNOWN')=0
            FROM read_parquet(?)
            """,
            [str(outcomes)],
        ),
        "executable_prices_in_daily_range": one(
            connection,
            """
            SELECT count(*) FILTER(WHERE
              (exit_first_5m_bar_model_executable AND
                (exit_first_5m_vwap_resolved<exit_daily_low-0.011
                 OR exit_first_5m_vwap_resolved>exit_daily_high+0.011
                 OR exit_first_5m_vwap_resolved<=exit_lower_limit+1e-9))
              OR (exit_to_1000_bar_model_executable AND
                (exit_to_1000_vwap_resolved<exit_daily_low-0.011
                 OR exit_to_1000_vwap_resolved>exit_daily_high+0.011
                 OR exit_to_1000_vwap_resolved<=exit_lower_limit+1e-9)))=0
            FROM read_parquet(?)
            """,
            [str(outcomes)],
        ),
        "near_limit_executable_has_window_high_evidence": one(
            connection,
            """
            SELECT count(*) FILTER(WHERE
              (exit_first_5m_bar_model_executable
                AND exit_first_5m_vwap_resolved<=exit_lower_limit+0.0005
                AND coalesce(exit_first_5m_high_observed,0)
                    <=exit_lower_limit+0.0005)
              OR (exit_to_1000_bar_model_executable
                AND exit_to_1000_vwap_resolved<=exit_lower_limit+0.0005
                AND coalesce(exit_to_1000_high_observed,0)
                    <=exit_lower_limit+0.0005))=0
            FROM read_parquet(?)
            """,
            [str(outcomes)],
        ),
        "signal_table_has_no_future_columns": not banned_columns,
    }

    report = json.loads(report_path.read_text(encoding="utf-8"))
    counts = {
        "audited_rows": one(
            connection, "SELECT count(*) FROM read_parquet(?)", [str(audited)]
        ),
        "eligible_rows": one(
            connection, "SELECT count(*) FROM read_parquet(?)", [str(eligible)]
        ),
        "outcome_rows": one(
            connection, "SELECT count(*) FROM read_parquet(?)", [str(outcomes)]
        ),
        "eligible_turnover_boundary_ambiguous_rows": one(
            connection,
            """
            SELECT count(*) FROM read_parquet(?)
            WHERE turnover_5_10_precision_status='BOUNDARY_AMBIGUOUS'
            """,
            [str(eligible)],
        ),
    }
    checks["report_row_counts_match"] = (
        counts["audited_rows"] == report["metrics"]["row_count"]
        and counts["eligible_rows"] == report["metrics"]["eligible_feature_rows"]
        and counts["outcome_rows"] == report["metrics"]["exit_outcome_rows"]
    )
    status = "PASS" if all(checks.values()) else "FAIL"
    fingerprints = {}
    for label, path in (
        ("audited", audited),
        ("eligible_features", eligible),
        ("exit_outcomes", outcomes),
    ):
        digest, size = fingerprint(path)
        fingerprints[label] = {"path": str(path), "sha256": digest, "bytes": size}
    result = {
        "status": status,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
        "counts": counts,
        "eligible_column_count": len(eligible_columns),
        "banned_signal_columns_found": banned_columns,
        "fingerprints": fingerprints,
    }
    verification_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 2024 年工程冻结集独立验证",
        "",
        f"- 验证状态：**{status}**",
        f"- 生成时间：{result['created_at']}",
        f"- 审计/信号特征/退出结果：{counts['audited_rows']:,}/{counts['eligible_rows']:,}/{counts['outcome_rows']:,}",
        f"- 5%/10%换手率舍入边界不确定：{counts['eligible_turnover_boundary_ambiguous_rows']} 行",
        f"- 信号时点表字段数：{len(eligible_columns)}；禁用未来字段：{len(banned_columns)}",
        "",
        "## 不变量",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} `{name}`" for name, passed in checks.items()
    )
    lines.extend(
        [
            "",
            "## 结论边界",
            "",
            "- 本验证只证明2024年5分钟工程数据集的集合、时点字段和退出分类自洽。",
            "- 不运行回测、不评价收益、不选择参数；1分钟尾盘结构和第一分钟退出仍未验证。",
        ]
    )
    verification_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if status != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
