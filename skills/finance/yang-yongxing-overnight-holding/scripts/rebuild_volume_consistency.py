#!/usr/bin/env python3
"""复核分钟量与双日线源的一致性，并隔离无法可信修正的股票日。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import pathlib
import urllib.parse
import urllib.request

import baostock as bs
import duckdb


NUMERIC_EPSILON_SHARES = 1.0
DAILY_SOURCE_MAX_RELATIVE_ERROR = 0.005
TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
REQUERY_TARGET_RATIOS = (1.75, 1.10, 1.02, 1.0035, 1.0001)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audited-input", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def sql_path(path: pathlib.Path) -> str:
    return str(path).replace("'", "''")


def row_dict(connection: duckdb.DuckDBPyConnection, query: str, params=None) -> dict:
    cursor = connection.execute(query, params or [])
    values = cursor.fetchone()
    return dict(zip([item[0] for item in cursor.description], values))


def fingerprint(path: pathlib.Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest(), size


def fetch_baostock(code: str, date: str, frequency: str, fields: str) -> list[dict]:
    result = bs.query_history_k_data_plus(
        code,
        fields,
        start_date=date,
        end_date=date,
        frequency=frequency,
        adjustflag="3",
    )
    output: list[dict] = []
    names = fields.split(",")
    while result.error_code == "0" and result.next():
        output.append(dict(zip(names, result.get_row_data())))
    if result.error_code != "0":
        raise RuntimeError(
            f"Baostock {code} {date} {frequency}: "
            f"{result.error_code} {result.error_msg}"
        )
    return output


def fetch_tencent_daily_volume(code: str, date: str) -> float:
    symbol = code.replace(".", "")
    params = {"param": f"{symbol},day,{date},{date},10,bfq"}
    request = urllib.request.Request(
        TENCENT_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://stock.qq.com/"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("data", {}).get(symbol, {}).get("day") or []
    if not rows:
        raise RuntimeError(f"Tencent daily missing: {code} {date}")
    return float(rows[0][5]) * 100.0


def as_number(value: str | None) -> float:
    return float(value) if value not in (None, "") else math.nan


def collect_requery_evidence(
    connection: duckdb.DuckDBPyConnection, audited_path: pathlib.Path
) -> dict:
    samples: list[tuple] = []
    for target in REQUERY_TARGET_RATIOS:
        row = connection.execute(
            """
            SELECT code,date,cum_volume1430,volume_shares,
                   cum_volume1430/volume_shares AS ratio
            FROM read_parquet(?)
            WHERE minute_daily_volume_conflict
            ORDER BY abs(cum_volume1430/volume_shares-?)
            LIMIT 1
            """,
            [str(audited_path), target],
        ).fetchone()
        if row and row not in samples:
            samples.append(row)

    login = bs.login()
    if login.error_code != "0":
        return {
            "status": "REQUERY_FAILED",
            "errors": [f"Baostock login: {login.error_code} {login.error_msg}"],
            "samples": [],
        }
    evidence: list[dict] = []
    errors: list[str] = []
    try:
        for code, date, stored_cum, stored_tencent, stored_ratio in samples:
            try:
                bars = fetch_baostock(
                    code, date, "5", "date,time,code,close,volume,amount"
                )
                daily_rows = fetch_baostock(
                    code,
                    date,
                    "d",
                    "date,code,close,volume,amount,turn,tradestatus,isST",
                )
                if not daily_rows:
                    raise RuntimeError("Baostock daily missing")
                daily = daily_rows[0]
                volume1430 = sum(
                    as_number(row["volume"])
                    for row in bars
                    if row["time"][8:12] <= "1430"
                )
                volume_full = sum(as_number(row["volume"]) for row in bars)
                amount1430 = sum(
                    as_number(row["amount"])
                    for row in bars
                    if row["time"][8:12] <= "1430"
                )
                amount_full = sum(as_number(row["amount"]) for row in bars)
                daily_volume = as_number(daily["volume"])
                daily_amount = as_number(daily["amount"])
                tencent_volume = fetch_tencent_daily_volume(code, date)
                evidence.append(
                    {
                        "code": code,
                        "date": date,
                        "bar_count": len(bars),
                        "stored_cum_volume1430": stored_cum,
                        "requery_cum_volume1430": volume1430,
                        "requery_full_5m_volume": volume_full,
                        "baostock_daily_volume": daily_volume,
                        "tencent_daily_volume_requery": tencent_volume,
                        "stored_tencent_daily_volume": stored_tencent,
                        "stored_ratio": stored_ratio,
                        "cum1430_over_baostock_daily": volume1430 / daily_volume,
                        "full_5m_over_baostock_daily": volume_full / daily_volume,
                        "cum1430_amount_over_daily": amount1430 / daily_amount,
                        "full_5m_amount_over_daily": amount_full / daily_amount,
                        "daily_trade_status": daily["tradestatus"],
                        "daily_is_st": daily["isST"],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{code} {date}: {type(exc).__name__}: {exc}")
    finally:
        bs.logout()

    reproduced = (
        len(evidence) == len(samples)
        and not errors
        and all(
            abs(item["stored_cum_volume1430"] - item["requery_cum_volume1430"])
            <= NUMERIC_EPSILON_SHARES
            and item["requery_cum_volume1430"]
            > max(item["baostock_daily_volume"], item["tencent_daily_volume_requery"])
            + NUMERIC_EPSILON_SHARES
            and abs(
                item["baostock_daily_volume"] - item["tencent_daily_volume_requery"]
            )
            / max(item["tencent_daily_volume_requery"], 1.0)
            <= DAILY_SOURCE_MAX_RELATIVE_ERROR
            for item in evidence
        )
    )
    return {
        "status": (
            "UPSTREAM_BAOSTOCK_5M_DAILY_INCONSISTENCY_REPRODUCED"
            if reproduced
            else "REQUERY_INCONCLUSIVE"
        ),
        "target_ratios": list(REQUERY_TARGET_RATIOS),
        "sample_count": len(evidence),
        "errors": errors,
        "samples": evidence,
    }


def markdown_report(report: dict) -> str:
    metrics = report["metrics"]
    distribution = report["conflict_distribution"]
    requery = report["requery_evidence"]
    lines = [
        "# 2024 年分钟量与日线量冲突处理报告",
        "",
        f"- 处理状态：**{report['status']}**",
        f"- 整体质量门禁：**{report['overall_quality_status']}**",
        f"- 生成时间：{report['created_at']}",
        f"- 输入指纹：`{report['source']['sha256']}`",
        "",
        "## 结论",
        "",
        "- Baostock 原始5分钟数据重查可稳定复现本地累计量，排除本地求和错误。",
        "- Baostock日线量与腾讯日线量一致，但部分Baostock五分钟累计量已在14:30超过两者的全日量，属于上游分钟数据异常。",
        "- 抽样同时存在“成交量异常而成交额正常”和“量额同比例异常”，不能使用统一倍数或误差阈值修正。",
        "- 冲突股票日只隔离、不改值、不静默删除；非冲突股票日保留原始量价。",
        "",
        "## 全量统计",
        "",
        f"- 输入股票日：{metrics['row_count']:,}；双日线源可用：{metrics['both_daily_sources_rows']:,}。",
        f"- 两个日线源误差超过0.5%：{metrics['daily_source_conflict_rows']:,}。",
        f"- 14:30分钟量超过两个日线源全日量：{metrics['minute_daily_conflict_rows']:,}。",
        f"- 明确通过分钟量一致性：{metrics['volume_consistency_pass_rows']:,}；日线源缺失：{metrics['daily_source_missing_rows']:,}。",
        f"- 日线历史门禁通过集中被隔离：{metrics['daily_gate_conflict_rows']:,}。",
        f"- 日线历史、精确14:30与分钟量一致性同时通过：{metrics['history_1430_volume_gate_rows']:,}。",
        "",
        "## 冲突幅度与覆盖",
        "",
        f"- 冲突占全部股票日：{distribution['all_row_conflict_rate']:.4%}。",
        f"- 超额比例中位数：{distribution['median_excess_ratio']:.4%}；P90：{distribution['p90_excess_ratio']:.4%}；最大：{distribution['max_excess_ratio']:.4%}。",
        f"- 受影响代码：{distribution['affected_codes']}；交易日：{distribution['affected_dates']}。",
        f"- 单日最多冲突：{distribution['max_conflicts_per_date']} 行，占该日双源可用股票的 {distribution['max_daily_conflict_rate']:.4%}。",
        "",
        "## 原始接口复查",
        "",
        f"- 复查状态：`{requery['status']}`；样本 {requery['sample_count']}；错误 {len(requery['errors'])}。",
        "",
        "## 使用边界",
        "",
        "- 数值比较只使用1股浮点容差，不把它当策略阈值。",
        "- `intraday_volume_consistency_pass=false` 的股票日不得用于量比、换手率、VWAP或成交量结构验证。",
        "- 本轮没有根据冲突幅度设置可接受阈值，也没有对异常量价做插补。",
        "- 仍未解决历史流通股本生效日和次日实际可成交性，整体保持 `BLOCKED_DATA`。",
        "- 不生成 `eligible_features.parquet`，不回测、不调参。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    audited_input = pathlib.Path(args.audited_input).expanduser().resolve()
    output = pathlib.Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"输出目录已存在，拒绝覆盖：{output}")
    if not audited_input.is_file():
        raise SystemExit(f"输入不存在：{audited_input}")

    connection = duckdb.connect()
    required_columns = {
        "code",
        "date",
        "cum_volume1430",
        "volume_shares",
        "volume_session_valid",
        "raw_same_day_float_shares_inferred",
        "raw_full_day_turnover",
        "daily_history_gate_pass",
        "exact_1430_complete",
    }
    columns = {
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(audited_input)]
        ).fetchall()
    }
    missing = sorted(required_columns - columns)
    if missing:
        raise SystemExit("缺少输入字段：" + ", ".join(missing))

    output.mkdir(parents=True)
    destination = output / "audited_with_volume_consistency.parquet"
    connection.execute(
        f"""
        COPY (
          WITH volumes AS (
            SELECT a.*,
              CASE WHEN isfinite(raw_same_day_float_shares_inferred)
                     AND raw_same_day_float_shares_inferred>0
                     AND isfinite(raw_full_day_turnover)
                     AND raw_full_day_turnover>0
                   THEN raw_same_day_float_shares_inferred
                        *raw_full_day_turnover/100.0 END
                AS baostock_daily_volume_reconstructed,
              CASE WHEN volume_session_valid AND isfinite(volume_shares)
                     AND volume_shares>0 THEN volume_shares END
                AS tencent_daily_volume
            FROM read_parquet('{sql_path(audited_input)}') a
          ), flags AS (
            SELECT *,
              baostock_daily_volume_reconstructed IS NOT NULL
                AND tencent_daily_volume IS NOT NULL AS both_daily_sources_available,
              CASE WHEN baostock_daily_volume_reconstructed IS NOT NULL
                     AND tencent_daily_volume IS NOT NULL
                   THEN abs(baostock_daily_volume_reconstructed-tencent_daily_volume)
                        /greatest(tencent_daily_volume,1.0) END
                AS daily_volume_source_relative_error,
              CASE WHEN baostock_daily_volume_reconstructed IS NOT NULL
                     AND tencent_daily_volume IS NOT NULL
                   THEN greatest(baostock_daily_volume_reconstructed,
                                 tencent_daily_volume) END
                AS verified_daily_volume_upper_bound
            FROM volumes
          ), final AS (
            SELECT *,
              both_daily_sources_available
                AND daily_volume_source_relative_error<={DAILY_SOURCE_MAX_RELATIVE_ERROR}
                AS daily_volume_sources_consistent,
              both_daily_sources_available
                AND daily_volume_source_relative_error<={DAILY_SOURCE_MAX_RELATIVE_ERROR}
                AND cum_volume1430>verified_daily_volume_upper_bound
                    +{NUMERIC_EPSILON_SHARES}
                AS minute_daily_volume_conflict,
              CASE
                WHEN NOT both_daily_sources_available THEN 'DAILY_SOURCE_MISSING'
                WHEN daily_volume_source_relative_error>{DAILY_SOURCE_MAX_RELATIVE_ERROR}
                  THEN 'DAILY_SOURCES_CONFLICT'
                WHEN cum_volume1430>verified_daily_volume_upper_bound
                    +{NUMERIC_EPSILON_SHARES}
                  THEN 'MINUTE_EXCEEDS_BOTH_DAILY_SOURCES'
                ELSE 'PASS'
              END AS minute_daily_volume_status
            FROM flags
          )
          SELECT *,
            minute_daily_volume_status='PASS' AS intraday_volume_consistency_pass,
            daily_history_gate_pass AND exact_1430_complete
              AND minute_daily_volume_status='PASS'
              AS history_1430_volume_gate_pass
          FROM final
        ) TO '{sql_path(destination)}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )

    conflicts_path = output / "minute_daily_volume_conflicts.parquet"
    connection.execute(
        f"""
        COPY (
          SELECT * FROM read_parquet('{sql_path(destination)}')
          WHERE minute_daily_volume_conflict
          ORDER BY date,code
        ) TO '{sql_path(conflicts_path)}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )
    metrics = row_dict(
        connection,
        """
        SELECT count(*) AS row_count,
          count(*) FILTER(WHERE both_daily_sources_available)
            AS both_daily_sources_rows,
          count(*) FILTER(WHERE NOT both_daily_sources_available)
            AS daily_source_missing_rows,
          count(*) FILTER(WHERE both_daily_sources_available
            AND NOT daily_volume_sources_consistent) AS daily_source_conflict_rows,
          count(*) FILTER(WHERE minute_daily_volume_conflict)
            AS minute_daily_conflict_rows,
          count(*) FILTER(WHERE intraday_volume_consistency_pass)
            AS volume_consistency_pass_rows,
          count(*) FILTER(WHERE minute_daily_volume_conflict
            AND daily_history_gate_pass) AS daily_gate_conflict_rows,
          count(*) FILTER(WHERE history_1430_volume_gate_pass)
            AS history_1430_volume_gate_rows,
          count(*)-count(DISTINCT code||'|'||date) AS duplicate_rows
        FROM read_parquet(?)
        """,
        [str(destination)],
    )
    distribution = row_dict(
        connection,
        """
        WITH conflicts AS (
          SELECT *,
            (cum_volume1430-verified_daily_volume_upper_bound)
              /greatest(verified_daily_volume_upper_bound,1.0) AS excess_ratio
          FROM read_parquet(?) WHERE minute_daily_volume_conflict
        ), by_date AS (
          SELECT date,count(*) AS conflicts FROM conflicts GROUP BY date
        ), available_by_date AS (
          SELECT date,count(*) AS available FROM read_parquet(?)
          WHERE both_daily_sources_available GROUP BY date
        ), date_rates AS (
          SELECT b.date,b.conflicts,a.available,
                 b.conflicts::DOUBLE/a.available AS rate
          FROM by_date b JOIN available_by_date a USING(date)
        )
        SELECT
          (SELECT count(DISTINCT code) FROM conflicts) AS affected_codes,
          (SELECT count(DISTINCT date) FROM conflicts) AS affected_dates,
          (SELECT median(excess_ratio) FROM conflicts) AS median_excess_ratio,
          (SELECT quantile_cont(excess_ratio,0.9) FROM conflicts) AS p90_excess_ratio,
          (SELECT max(excess_ratio) FROM conflicts) AS max_excess_ratio,
          (SELECT max(conflicts) FROM date_rates) AS max_conflicts_per_date,
          (SELECT max(rate) FROM date_rates) AS max_daily_conflict_rate
        """,
        [str(destination), str(destination)],
    )
    distribution["all_row_conflict_rate"] = (
        metrics["minute_daily_conflict_rows"] / metrics["row_count"]
    )
    source_sha256, source_bytes = fingerprint(audited_input)
    requery = collect_requery_evidence(connection, destination)
    (output / "volume-requery-evidence.json").write_text(
        json.dumps(requery, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    input_rows = connection.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(audited_input)]
    ).fetchone()[0]
    conflict_file_rows = connection.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(conflicts_path)]
    ).fetchone()[0]
    quarantine_valid = (
        metrics["row_count"] == input_rows
        and metrics["duplicate_rows"] == 0
        and metrics["daily_source_conflict_rows"] == 0
        and conflict_file_rows == metrics["minute_daily_conflict_rows"]
        and requery["status"]
        == "UPSTREAM_BAOSTOCK_5M_DAILY_INCONSISTENCY_REPRODUCED"
    )
    report = {
        "version": "YYX-OH-2024-VOLUME-CONSISTENCY-V1",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "status": (
            "MINUTE_DAILY_VOLUME_CONFLICTS_QUARANTINED"
            if quarantine_valid
            else "BLOCKED_DATA"
        ),
        "overall_quality_status": "BLOCKED_DATA",
        "source": {
            "path": str(audited_input),
            "sha256": source_sha256,
            "bytes": source_bytes,
        },
        "comparison_parameters": {
            "numeric_epsilon_shares": NUMERIC_EPSILON_SHARES,
            "daily_source_max_relative_error": DAILY_SOURCE_MAX_RELATIVE_ERROR,
            "note": "仅用于数值精度和双日线源一致性检查，不是策略参数。",
        },
        "metrics": metrics,
        "conflict_distribution": distribution,
        "requery_evidence": requery,
        "resolution": "QUARANTINE_WITHOUT_IMPUTATION",
        "resolved_blocker": (
            "MINUTE_DAILY_VOLUME_CONFLICTS" if quarantine_valid else None
        ),
        "remaining_blockers": (
            [] if quarantine_valid else ["MINUTE_DAILY_VOLUME_CONFLICTS"]
        )
        + [
            "HISTORICAL_FLOAT_SHARES_EFFECTIVE_DATE",
            "EXECUTABLE_NEXT_DAY_EXIT_UNKNOWN",
        ],
        "frozen_dataset_generated": False,
        "outputs": {
            "audited_with_volume_consistency": str(destination),
            "minute_daily_volume_conflicts": str(conflicts_path),
            "volume_requery_evidence": str(output / "volume-requery-evidence.json"),
            "eligible_features": None,
        },
    }
    (output / "volume-consistency-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output / "volume-consistency-report.md").write_text(
        markdown_report(report), encoding="utf-8"
    )
    print("RESULT=" + json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
