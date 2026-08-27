#!/usr/bin/env python3
"""将精确 14:30 时间戳完整性证据接入安全日线审计表。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib

import duckdb


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--completeness-input", required=True)
    parser.add_argument("--audited-input", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def sql_path(path: pathlib.Path) -> str:
    return str(path).replace("'", "''")


def row_dict(connection: duckdb.DuckDBPyConnection, query: str, params=None) -> dict:
    cursor = connection.execute(query, params or [])
    values = cursor.fetchone()
    return dict(zip([item[0] for item in cursor.description], values))


def source_fingerprint(paths: list[pathlib.Path]) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    total_bytes = 0
    existing = sorted(path for path in paths if path.is_file())
    for path in existing:
        encoded = str(path).encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        size = path.stat().st_size
        total_bytes += size
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest(), len(existing), total_bytes


def markdown_report(report: dict) -> str:
    collection = report["collection"]
    source = report["completeness_source"]
    joined = report["joined"]
    comparison = report["comparison"]
    return "\n".join(
        [
            "# 2024 年 14:30 精确 K 线完整性修复报告",
            "",
            f"- 修复状态：**{report['status']}**",
            f"- 整体质量门禁：**{report['overall_quality_status']}**",
            f"- 生成时间：{report['created_at']}",
            f"- 数据源：{report['source_name']}",
            f"- 源数据指纹：`{report['source']['sha256']}`",
            "",
            "## 补采覆盖",
            "",
            f"- 代码完成：{collection['completed_codes']} / {collection['total_codes']}，未解决失败 {collection['unresolved_failures']}。",
            f"- 精确完整性股票日：{source['row_count']:,}；代码 {source['observed_codes']}；交易日 {source['trading_dates']}。",
            f"- 重复 code-date：{source['duplicate_code_date_rows']}。",
            f"- 截至14:30时间戳乱序股票日：{source['out_of_order_rows']:,}。",
            "",
            "## 14:30 精确结果",
            "",
            f"- 精确完整：{source['exact_1430_complete_rows']:,} 行。",
            f"- 不完整并已明确标记：{source['exact_1430_incomplete_rows']:,} 行。",
            f"- 截至 14:30 根数不是 42：{source['bad_bar_count1430_rows']:,} 行。",
            f"- 存在重复时间戳：{source['duplicate_1430_rows']:,} 行；缺少预期时间戳：{source['missing_1430_rows']:,} 行。",
            f"- 缺少唯一 14:30 K 线：{source['missing_unique_1430_bar_rows']:,} 行；存在非预期时间戳：{source['unexpected_1430_rows']:,} 行。",
            "",
            "## 与原审计表连接",
            "",
            f"- 输入/输出行数：{joined['audited_input_rows']:,} / {joined['joined_rows']:,}；输出重复 {joined['joined_duplicate_rows']}。",
            f"- 缺少精确完整性连接：{joined['missing_completeness_rows']:,} 行。",
            f"- 原全天代理通过、精确14:30失败：{comparison['proxy_true_exact_false_rows']:,} 行。",
            f"- 原全天代理失败、精确14:30通过：{comparison['proxy_false_exact_true_rows']:,} 行。",
            "",
            "## 使用边界",
            "",
            "- `exact_1430_complete` 逐个检查 09:35—14:30 的 42 个预期时间戳、重复、缺失、非预期时间戳、14:30 根及源顺序。",
            "- 原 `intraday_complete` 依赖 15:00 后才完整可见的全天 48 根，只保留作对照，不再用于证明 14:30 时点完整性。",
            "- 不完整股票日保留在审计表并明确标记，不静默删除。",
            "- 本轮不处理历史流通股本、分钟量与日线量冲突或次日实际可成交性。",
            "- 整体门禁继续为 `BLOCKED_DATA`，不生成 `eligible_features.parquet`，不回测、不调参。",
        ]
    ) + "\n"


def main() -> None:
    args = parse_args()
    completeness_root = pathlib.Path(args.completeness_input).expanduser().resolve()
    audited_input = pathlib.Path(args.audited_input).expanduser().resolve()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"输出目录已存在，拒绝覆盖：{output}")

    state_path = completeness_root / "state.json"
    codes_path = completeness_root / "codes.json"
    parts = sorted((completeness_root / "completeness").glob("part-*.parquet"))
    missing = [
        str(path)
        for path in (state_path, codes_path, audited_input)
        if not path.is_file()
    ]
    if not parts:
        missing.append(str(completeness_root / "completeness" / "part-*.parquet"))
    if missing:
        raise SystemExit("缺少输入文件：" + "、".join(missing))

    state = json.loads(state_path.read_text(encoding="utf-8"))
    codes = json.loads(codes_path.read_text(encoding="utf-8"))
    completed = set(state.get("completed_codes", []))
    unresolved = sorted(
        {item["code"] for item in state.get("failures", [])} - completed
    )
    pending = sorted(set(codes) - completed)
    if pending or unresolved:
        raise SystemExit(
            f"完整性补采未完成：pending={len(pending)} unresolved={len(unresolved)}"
        )

    output.mkdir(parents=True)
    connection = duckdb.connect()
    parts_glob = str(completeness_root / "completeness" / "*.parquet")
    completeness_columns = {
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [parts_glob]
        ).fetchall()
    }
    order_check_column = (
        "source_out_of_order_count1430"
        if "source_out_of_order_count1430" in completeness_columns
        else "source_out_of_order_count"
    )

    source = row_dict(
        connection,
        f"""
        SELECT count(*) AS row_count,
          count(DISTINCT code) AS observed_codes,
          count(DISTINCT date) AS trading_dates,
          count(*)-count(DISTINCT code||'|'||date) AS duplicate_code_date_rows,
          min(date) AS min_date,max(date) AS max_date,
          count(*) FILTER(WHERE exact_1430_complete) AS exact_1430_complete_rows,
          count(*) FILTER(WHERE NOT exact_1430_complete) AS exact_1430_incomplete_rows,
          count(*) FILTER(WHERE bar_count1430<>42) AS bad_bar_count1430_rows,
          count(*) FILTER(WHERE duplicate_bar_count1430>0) AS duplicate_1430_rows,
          count(*) FILTER(WHERE missing_expected_bar_count1430>0) AS missing_1430_rows,
          count(*) FILTER(WHERE NOT has_1430_bar) AS missing_unique_1430_bar_rows,
          count(*) FILTER(WHERE unexpected_bar_count1430>0) AS unexpected_1430_rows,
          count(*) FILTER(WHERE {order_check_column}>0) AS out_of_order_rows
        FROM read_parquet(?)
        """,
        [parts_glob],
    )
    if source["duplicate_code_date_rows"]:
        raise SystemExit(
            f"完整性数据存在重复 code-date：{source['duplicate_code_date_rows']}"
        )

    incomplete_path = output / "incomplete_1430_rows.parquet"
    connection.execute(
        f"""
        COPY (
          SELECT * FROM read_parquet('{sql_path(pathlib.Path(parts_glob))}')
          WHERE NOT exact_1430_complete
          ORDER BY date,code
        ) TO '{sql_path(incomplete_path)}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )

    audited_input_rows = connection.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(audited_input)]
    ).fetchone()[0]
    destination = output / "audited_with_1430_completeness.parquet"
    connection.execute(
        f"""
        COPY (
          SELECT a.*,
            c.code IS NOT NULL AS completeness_row_present,
            c.bar_count AS exact_bar_count_full,
            c.distinct_bar_count AS exact_distinct_bar_count_full,
            c.duplicate_bar_count AS exact_duplicate_bar_count_full,
            c.unexpected_bar_count AS exact_unexpected_bar_count_full,
            c.missing_expected_bar_count AS exact_missing_expected_bar_count_full,
            c.source_out_of_order_count,
            c.{order_check_column} AS source_out_of_order_count1430,
            c.bar_count1430,c.distinct_bar_count1430,
            c.duplicate_bar_count1430,c.unexpected_bar_count1430,
            c.missing_expected_bar_count1430,c.has_1430_bar,
            coalesce(c.exact_1430_complete,false) AS exact_1430_complete,
            coalesce(c.exact_1430_complete,false) AS intraday_1430_gate_pass
          FROM read_parquet('{sql_path(audited_input)}') a
          LEFT JOIN read_parquet('{sql_path(pathlib.Path(parts_glob))}') c
          USING(code,date)
        ) TO '{sql_path(destination)}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )

    joined = row_dict(
        connection,
        """
        SELECT count(*) AS joined_rows,
          count(*)-count(DISTINCT code||'|'||date) AS joined_duplicate_rows,
          count(*) FILTER(WHERE NOT completeness_row_present)
            AS missing_completeness_rows,
          count(*) FILTER(WHERE exact_1430_complete) AS exact_1430_complete_rows,
          count(*) FILTER(WHERE intraday_1430_gate_pass) AS intraday_1430_gate_rows
        FROM read_parquet(?)
        """,
        [str(destination)],
    )
    joined["audited_input_rows"] = audited_input_rows
    comparison = row_dict(
        connection,
        """
        SELECT
          count(*) FILTER(WHERE intraday_complete AND NOT exact_1430_complete)
            AS proxy_true_exact_false_rows,
          count(*) FILTER(WHERE NOT intraday_complete AND exact_1430_complete)
            AS proxy_false_exact_true_rows,
          count(*) FILTER(WHERE intraday_complete AND exact_1430_complete)
            AS both_complete_rows,
          count(*) FILTER(WHERE NOT intraday_complete AND NOT exact_1430_complete)
            AS both_incomplete_rows
        FROM read_parquet(?)
        """,
        [str(destination)],
    )

    repaired = (
        len(completed) == len(codes)
        and not unresolved
        and source["duplicate_code_date_rows"] == 0
        and joined["joined_rows"] == audited_input_rows
        and joined["joined_duplicate_rows"] == 0
        and joined["missing_completeness_rows"] == 0
    )
    fingerprint, file_count, source_bytes = source_fingerprint(
        parts + [state_path, codes_path, audited_input]
    )
    report = {
        "version": "YYX-OH-2024-EXACT-1430-COMPLETENESS-V1",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": (
            "EXACT_1430_COMPLETENESS_REPAIRED" if repaired else "BLOCKED_DATA"
        ),
        "overall_quality_status": "BLOCKED_DATA",
        "source_name": "Baostock 5-minute date/time/code backfill",
        "source": {
            "sha256": fingerprint,
            "file_count": file_count,
            "bytes": source_bytes,
        },
        "collection": {
            "total_codes": len(codes),
            "completed_codes": len(completed),
            "unresolved_failures": len(unresolved),
        },
        "completeness_source": source,
        "order_check_source_column": order_check_column,
        "joined": joined,
        "comparison": comparison,
        "resolved_blocker": (
            "EXACT_1430_BAR_COMPLETENESS" if repaired else None
        ),
        "remaining_blockers": (
            [] if repaired else ["EXACT_1430_BAR_COMPLETENESS"]
        )
        + [
            "HISTORICAL_FLOAT_SHARES_EFFECTIVE_DATE",
            "MINUTE_DAILY_VOLUME_CONFLICTS",
            "EXECUTABLE_NEXT_DAY_EXIT_UNKNOWN",
        ],
        "frozen_dataset_generated": False,
        "outputs": {
            "audited_with_1430_completeness": str(destination),
            "incomplete_1430_rows": str(incomplete_path),
            "eligible_features": None,
        },
    }
    (output / "1430-completeness-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output / "1430-completeness-report.md").write_text(
        markdown_report(report), encoding="utf-8"
    )
    print("RESULT=" + json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
