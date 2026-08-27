#!/usr/bin/env python3
"""用完整交易日历重算无停牌污染的历史日线窗口。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib

import duckdb
import pyarrow as pa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-input", required=True)
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
    source = report["daily_source"]
    rebuilt = report["rebuilt"]
    comparison = report["comparison"]
    return "\n".join(
        [
            "# 2024 年安全日线窗口重算报告",
            "",
            f"- 日线修复状态：**{report['status']}**",
            f"- 生成时间：{report['created_at']}",
            f"- 数据源：{report['source_name']}",
            f"- 源数据指纹：`{report['source']['sha256']}`",
            "",
            "## 采集与覆盖",
            "",
            f"- 代码完成：{collection['completed_codes']} / {collection['total_codes']}，未解决失败 {collection['unresolved_failures']}。",
            f"- 日线记录：{source['row_count']:,}，实际有日线代码 {source['observed_codes']}。",
            f"- 交易日历：{source['calendar_days']} 日，{source['calendar_min_date']} 至 {source['calendar_max_date']}。",
            f"- 日线重复 code-date：{source['duplicate_rows']}。",
            "",
            "## 安全窗口结果",
            "",
            f"- 2024 日历面板：{rebuilt['safe_daily_rows']:,} 行；与五分钟审计表连接：{rebuilt['joined_rows']:,} 行。",
            f"- 当前日线正常：{rebuilt['current_volume_session_rows']:,} 行；复牌日：{rebuilt['resume_rows']:,} 行。",
            f"- 前5日窗口完整：{rebuilt['prev5_complete_rows']:,} 行。",
            f"- 前20日窗口完整：{rebuilt['recent20_complete_rows']:,} 行。",
            f"- D-3 至 D-1 的120日均量窗口完整：{rebuilt['volume3_complete_rows']:,} 行。",
            f"- 三项历史窗口、当前状态、ST、上市60日与复牌排除同时通过：{rebuilt['daily_history_gate_rows']:,} 行。",
            "",
            "## 与旧字段对比",
            "",
            f"- 旧 `recent20_complete` 为真但安全窗口不完整：{comparison['old_recent20_true_safe_incomplete']:,} 行。",
            f"- 两边窗口都完整时，`recent_strong` 结果不一致：{comparison['recent_strong_disagreements']:,} 行。",
            f"- 旧 `volume3_complete` 为真但安全窗口不完整：{comparison['old_volume3_true_safe_incomplete']:,} 行。",
            f"- 两边窗口都完整时，`volume3_ok` 结果不一致：{comparison['volume3_ok_disagreements']:,} 行。",
            f"- 14:30 五分钟累计量超过腾讯全日日线量：{comparison['minute_daily_volume_upper_bound_rows']:,} 行。",
            "",
            "## 使用边界",
            "",
            "- 本轮只修复日线历史窗口和复牌识别，不验证热门板块、尾盘结构或收益。",
            "- 腾讯不复权收盘价用于计算普通交易日相邻涨跌幅；除权除息日涨跌幅标记为不可用，使相关20日窗口保守地不完整。",
            "- 成交量使用腾讯原始手数乘100得到股数。",
            "- `daily_history_gate_pass` 是数据完整性标记，不是策略入选信号。",
            "- 历史流通股本有效日期和14:30精确分钟完整性仍未解决，整体质量门禁继续保持 `BLOCKED_DATA`。",
            "- 不生成 `eligible_features.parquet`，也不进行回测或参数调整。",
        ]
    ) + "\n"


def main() -> None:
    args = parse_args()
    daily_root = pathlib.Path(args.daily_input).expanduser().resolve()
    audited_input = pathlib.Path(args.audited_input).expanduser().resolve()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"输出目录已存在，拒绝覆盖：{output}")

    state_path = daily_root / "state.json"
    calendar_path = daily_root / "trade_calendar.parquet"
    daily_parts = sorted((daily_root / "daily").glob("part-*.parquet"))
    required = [state_path, calendar_path, audited_input]
    missing = [str(path) for path in required if not path.is_file()]
    if not daily_parts:
        missing.append(str(daily_root / "daily" / "part-*.parquet"))
    if missing:
        raise SystemExit("缺少输入文件：" + "、".join(missing))

    state = json.loads(state_path.read_text(encoding="utf-8"))
    codes_path = pathlib.Path(state["parameters"]["codes"]).expanduser().resolve()
    codes = json.loads(codes_path.read_text(encoding="utf-8"))
    completed = set(state.get("completed_codes", []))
    unresolved = sorted(
        {item["code"] for item in state.get("failures", [])} - completed
    )
    if set(codes) - completed or unresolved:
        raise SystemExit(
            f"日线采集未完成：pending={len(set(codes)-completed)} "
            f"unresolved={len(unresolved)}"
        )

    output.mkdir(parents=True)
    connection = duckdb.connect()
    connection.register("codes_source", pa.table({"code": codes}))
    daily_glob = str(daily_root / "daily" / "*.parquet")

    daily_source = row_dict(
        connection,
        """
        SELECT count(*) AS row_count,count(DISTINCT code) AS observed_codes,
          count(*)-count(DISTINCT code||'|'||date) AS duplicate_rows,
          min(date) AS min_date,max(date) AS max_date
        FROM read_parquet(?)
        """,
        [daily_glob],
    )
    daily_source.update(
        row_dict(
            connection,
            """
            SELECT count(*) AS calendar_days,min(date) AS calendar_min_date,
                   max(date) AS calendar_max_date
            FROM read_parquet(?)
            """,
            [str(calendar_path)],
        )
    )
    if daily_source["duplicate_rows"] != 0:
        raise SystemExit(f"日线存在重复 code-date：{daily_source['duplicate_rows']}")

    safe_path = output / "safe_daily_features.parquet"
    connection.execute(
        f"""
        COPY (
          WITH calendar AS (
            SELECT date,row_number() OVER(ORDER BY date) AS seq
            FROM read_parquet('{sql_path(calendar_path)}')
          ), daily AS (
            SELECT * FROM read_parquet('{sql_path(pathlib.Path(daily_glob))}')
          ), panel_base AS (
            SELECT c.code,cal.date,cal.seq,
                   d.open_bfq,d.high_bfq,d.low_bfq,d.close_bfq,
                   d.volume_shares,d.pct_chg_bfq,d.corporate_action_json,
                   d.code IS NOT NULL AS daily_row_present,
                   coalesce(d.code IS NOT NULL AND isfinite(d.volume_shares)
                     AND d.volume_shares>0,false) AS volume_session_valid,
                   coalesce(d.code IS NOT NULL AND isfinite(d.volume_shares)
                     AND d.volume_shares>0 AND isfinite(d.pct_chg_bfq),false)
                     AS strong_session_valid
            FROM codes_source c CROSS JOIN calendar cal
            LEFT JOIN daily d USING(code,date)
          ), panel_windows AS (
            SELECT *,
              min(CASE WHEN daily_row_present THEN seq END)
                OVER(PARTITION BY code) AS first_observed_seq,
              count(*) FILTER(WHERE volume_session_valid) OVER (
                PARTITION BY code ORDER BY seq
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
              ) AS prior_valid_session_count,
              count(*) FILTER(WHERE volume_session_valid) OVER (
                PARTITION BY code ORDER BY seq
                ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
              ) AS valid_volume_120,
              avg(volume_shares) FILTER(WHERE volume_session_valid) OVER (
                PARTITION BY code ORDER BY seq
                ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
              ) AS mean_volume_120,
              count(*) FILTER(WHERE volume_session_valid) OVER (
                PARTITION BY code ORDER BY seq
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
              ) AS valid_volume_prev5,
              avg(volume_shares) FILTER(WHERE volume_session_valid) OVER (
                PARTITION BY code ORDER BY seq
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
              ) AS mean_volume_prev5,
              count(*) FILTER(WHERE strong_session_valid) OVER (
                PARTITION BY code ORDER BY seq
                ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
              ) AS valid_strong_prev20,
              max(CASE WHEN strong_session_valid AND round(pct_chg_bfq,8)>=5.0
                       THEN 1 ELSE 0 END) OVER (
                PARTITION BY code ORDER BY seq
                ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
              ) AS strong_prev20,
              lag(volume_session_valid,1) OVER w AS volume_valid_d1
            FROM panel_base
            WINDOW w AS (PARTITION BY code ORDER BY seq)
          ), day_flags AS (
            SELECT *,
              CASE WHEN volume_session_valid AND valid_volume_120=120
                   THEN volume_shares>mean_volume_120 END AS above_ma120_safe
            FROM panel_windows
          ), history AS (
            SELECT *,
              lag(above_ma120_safe,1) OVER w AS ma120_ok_d1,
              lag(above_ma120_safe,2) OVER w AS ma120_ok_d2,
              lag(above_ma120_safe,3) OVER w AS ma120_ok_d3
            FROM day_flags
            WINDOW w AS (PARTITION BY code ORDER BY seq)
          )
          SELECT code,date,seq,daily_row_present,volume_session_valid,
            strong_session_valid,open_bfq,high_bfq,low_bfq,close_bfq,
            volume_shares,pct_chg_bfq,corporate_action_json,
            CASE WHEN first_observed_seq IS NOT NULL
                 THEN seq-first_observed_seq END AS listing_market_days_prior_safe,
            valid_volume_prev5=5 AS prev5_complete_safe,
            CASE WHEN valid_volume_prev5=5 THEN mean_volume_prev5 END
              AS prev5_volume_safe,
            valid_strong_prev20=20 AS recent20_complete_safe,
            valid_strong_prev20=20 AND strong_prev20=1 AS recent_strong_safe,
            ma120_ok_d1 IS NOT NULL AND ma120_ok_d2 IS NOT NULL
              AND ma120_ok_d3 IS NOT NULL AS volume3_complete_safe,
            coalesce(ma120_ok_d1,false) AND coalesce(ma120_ok_d2,false)
              AND coalesce(ma120_ok_d3,false) AS volume3_ok_safe,
            volume_session_valid AND prior_valid_session_count>0
              AND NOT coalesce(volume_valid_d1,false) AS is_resume_day_safe
          FROM history
          WHERE date BETWEEN '2024-01-02' AND '2024-12-31'
        ) TO '{sql_path(safe_path)}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )

    joined_path = output / "audited_with_safe_daily.parquet"
    connection.execute(
        f"""
        COPY (
          SELECT a.*,s.* EXCLUDE(code,date),
            a.trade_status=1 AND NOT a.is_st
              AND s.volume_session_valid
              AND s.listing_market_days_prior_safe>=60
              AND s.prev5_complete_safe
              AND s.recent20_complete_safe
              AND s.volume3_complete_safe
              AND NOT s.is_resume_day_safe AS daily_history_gate_pass,
            a.cum_volume1430>s.volume_shares+1
              AS minute_daily_volume_upper_bound_violation_tencent
          FROM read_parquet('{sql_path(audited_input)}') a
          JOIN read_parquet('{sql_path(safe_path)}') s USING(code,date)
        ) TO '{sql_path(joined_path)}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )

    rebuilt = row_dict(
        connection,
        """
        SELECT
          (SELECT count(*) FROM read_parquet(?)) AS safe_daily_rows,
          count(*) AS joined_rows,
          count(*) FILTER(WHERE volume_session_valid) AS current_volume_session_rows,
          count(*) FILTER(WHERE is_resume_day_safe) AS resume_rows,
          count(*) FILTER(WHERE prev5_complete_safe) AS prev5_complete_rows,
          count(*) FILTER(WHERE recent20_complete_safe) AS recent20_complete_rows,
          count(*) FILTER(WHERE volume3_complete_safe) AS volume3_complete_rows,
          count(*) FILTER(WHERE daily_history_gate_pass) AS daily_history_gate_rows
        FROM read_parquet(?)
        """,
        [str(safe_path), str(joined_path)],
    )
    comparison = row_dict(
        connection,
        """
        SELECT
          count(*) FILTER(WHERE recent20_complete AND NOT recent20_complete_safe)
            AS old_recent20_true_safe_incomplete,
          count(*) FILTER(WHERE recent20_complete AND recent20_complete_safe
            AND recent_strong IS DISTINCT FROM recent_strong_safe)
            AS recent_strong_disagreements,
          count(*) FILTER(WHERE volume3_complete AND NOT volume3_complete_safe)
            AS old_volume3_true_safe_incomplete,
          count(*) FILTER(WHERE volume3_complete AND volume3_complete_safe
            AND volume3_ok IS DISTINCT FROM volume3_ok_safe)
            AS volume3_ok_disagreements,
          count(*) FILTER(WHERE minute_daily_volume_upper_bound_violation_tencent)
            AS minute_daily_volume_upper_bound_rows
        FROM read_parquet(?)
        """,
        [str(joined_path)],
    )

    fingerprint_paths = daily_parts + [calendar_path, state_path, audited_input]
    fingerprint, file_count, source_bytes = source_fingerprint(fingerprint_paths)
    report = {
        "version": "YYX-OH-2024-SAFE-DAILY-V1",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": "DAILY_WINDOWS_REPAIRED",
        "source_name": "Tencent bfq daily + Baostock trade calendar + Baostock 2024 status",
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
        "daily_source": daily_source,
        "rebuilt": rebuilt,
        "comparison": comparison,
        "remaining_blockers": [
            "HISTORICAL_FLOAT_SHARES_EFFECTIVE_DATE",
            "EXACT_1430_BAR_COMPLETENESS",
            "MINUTE_DAILY_VOLUME_CONFLICTS",
            "EXECUTABLE_NEXT_DAY_EXIT_UNKNOWN",
        ],
        "outputs": {
            "safe_daily_features": str(safe_path),
            "audited_with_safe_daily": str(joined_path),
        },
    }
    (output / "daily-repair-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output / "daily-repair-report.md").write_text(
        markdown_report(report), encoding="utf-8"
    )
    print("RESULT=" + json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
