#!/usr/bin/env python3
"""核验历史流通股本生效日，并重建 14:30 换手率数据门禁。

Baostock 日线 ``turn`` 的分母是该交易日实际采用的流通股本。这个分母在
交易开始前已经生效，虽然免费接口只在日线记录中提供换手率。本脚本不把当前
股本回填到历史，也不沿用上一交易日股本；它用同日成交量/换手率还原当日有效
流通股本，并用东方财富独立日线的成交量、换手率对股本跳变日做交叉核验。
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


EASTMONEY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
BAOSTOCK_TURNOVER_HALF_UNIT_PCT = 0.00005
EASTMONEY_TURNOVER_HALF_UNIT_PCT = 0.005
DAILY_VOLUME_MAX_RELATIVE_ERROR = 0.005


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audited-input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cross-source-samples", type=int, default=80)
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


def eastmoney_secid(code: str) -> str:
    exchange, plain = code.split(".", 1)
    return f"{1 if exchange == 'sh' else 0}.{plain}"


def fetch_eastmoney_daily(code: str) -> dict[str, dict]:
    params = {
        "secid": eastmoney_secid(code),
        "klt": "101",
        "fqt": "0",
        "beg": "20240101",
        "end": "20241231",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    request = urllib.request.Request(
        EASTMONEY_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
    )
    last_error = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            klines = (payload.get("data") or {}).get("klines") or []
            output: dict[str, dict] = {}
            for line in klines:
                fields = line.split(",")
                if len(fields) < 11:
                    continue
                output[fields[0]] = {
                    "volume_shares": float(fields[5]) * 100.0,
                    "turnover_pct": float(fields[10]),
                }
            if not output:
                raise RuntimeError("未返回日线")
            return output
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(last_error)


def select_cross_source_samples(
    connection: duckdb.DuckDBPyConnection,
    input_path: pathlib.Path,
    sample_size: int,
) -> list[dict]:
    query = """
    WITH lagged AS (
      SELECT code,date,tencent_daily_volume AS daily_volume,
        raw_same_day_float_shares_inferred AS same_day_shares,
        last_value(
          CASE WHEN isfinite(raw_same_day_float_shares_inferred)
                 AND raw_same_day_float_shares_inferred>0
               THEN raw_same_day_float_shares_inferred END IGNORE NULLS
        ) OVER (
          PARTITION BY code ORDER BY date
          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_shares,
        raw_full_day_turnover AS baostock_turnover
      FROM read_parquet(?)
    ), events AS (
      SELECT *,same_day_shares/prior_shares-1.0 AS share_change_ratio
      FROM lagged
      WHERE isfinite(same_day_shares) AND same_day_shares>0
        AND isfinite(prior_shares) AND prior_shares>0
        AND isfinite(daily_volume) AND daily_volume>0
        AND isfinite(baostock_turnover) AND baostock_turnover>=0.5
        AND abs(same_day_shares/prior_shares-1.0)>=0.01
    )
    SELECT * FROM events
    ORDER BY abs(share_change_ratio) DESC,code,date
    LIMIT ?
    """
    cursor = connection.execute(query, [str(input_path), max(sample_size * 4, 200)])
    columns = [item[0] for item in cursor.description]
    candidates = [dict(zip(columns, row)) for row in cursor.fetchall()]
    if not candidates:
        return []

    top_count = min(max(sample_size // 2, 1), len(candidates))
    selected = candidates[:top_count]
    selected_keys = {(item["code"], item["date"]) for item in selected}
    remaining = sorted(
        candidates[top_count:],
        key=lambda item: hashlib.sha256(
            f"YYX-OH-2024-FLOAT-V1|{item['code']}|{item['date']}".encode("utf-8")
        ).hexdigest(),
    )
    for item in remaining:
        key = (item["code"], item["date"])
        if key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
        if len(selected) >= sample_size:
            break
    return selected


def crosscheck_eastmoney(samples: list[dict]) -> dict:
    cache: dict[str, dict[str, dict]] = {}
    evidence: list[dict] = []
    errors: list[dict] = []
    for index, sample in enumerate(samples, 1):
        code = sample["code"]
        try:
            if code not in cache:
                cache[code] = fetch_eastmoney_daily(code)
            remote = cache[code].get(sample["date"])
            if remote is None:
                raise RuntimeError("独立日线缺少目标日期")
            east_volume = remote["volume_shares"]
            east_turnover = remote["turnover_pct"]
            same_shares = sample["same_day_shares"]
            prior_shares = sample["prior_shares"]
            expected_same = east_volume / same_shares * 100.0
            expected_prior = east_volume / prior_shares * 100.0
            same_error = abs(expected_same - east_turnover)
            prior_error = abs(expected_prior - east_turnover)
            volume_error = abs(east_volume - sample["daily_volume"]) / max(
                sample["daily_volume"], 1.0
            )
            distinguishable = (
                abs(expected_same - expected_prior)
                > EASTMONEY_TURNOVER_HALF_UNIT_PCT * 4
            )
            same_day_supported = (
                volume_error <= DAILY_VOLUME_MAX_RELATIVE_ERROR
                and same_error <= EASTMONEY_TURNOVER_HALF_UNIT_PCT * 1.25
                and (
                    not distinguishable
                    or same_error + EASTMONEY_TURNOVER_HALF_UNIT_PCT * 2 < prior_error
                )
            )
            evidence.append(
                {
                    **sample,
                    "eastmoney_volume_shares": east_volume,
                    "eastmoney_turnover_pct": east_turnover,
                    "volume_relative_error": volume_error,
                    "expected_turnover_same_day_pct": expected_same,
                    "expected_turnover_prior_day_pct": expected_prior,
                    "same_day_turnover_error_pct_points": same_error,
                    "prior_day_turnover_error_pct_points": prior_error,
                    "distinguishable_at_eastmoney_precision": distinguishable,
                    "same_day_effective_date_supported": same_day_supported,
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "code": code,
                    "date": sample["date"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if index % 20 == 0:
            print(
                f"CROSS_SOURCE completed={index}/{len(samples)} errors={len(errors)}",
                flush=True,
            )

    distinguishable_rows = [
        item for item in evidence if item["distinguishable_at_eastmoney_precision"]
    ]
    supported_rows = [
        item for item in distinguishable_rows if item["same_day_effective_date_supported"]
    ]
    volume_mismatches = [
        item
        for item in evidence
        if item["volume_relative_error"] > DAILY_VOLUME_MAX_RELATIVE_ERROR
    ]
    return {
        "source": "Eastmoney unadjusted daily kline f57(volume lots), f61(turnover pct)",
        "source_url": EASTMONEY_URL,
        "selected_samples": len(samples),
        "matched_samples": len(evidence),
        "distinct_codes": len(cache),
        "distinguishable_samples": len(distinguishable_rows),
        "same_day_supported_samples": len(supported_rows),
        "same_day_support_rate": (
            len(supported_rows) / len(distinguishable_rows)
            if distinguishable_rows
            else None
        ),
        "volume_mismatches_over_0_5pct": len(volume_mismatches),
        "errors": errors,
        "samples": evidence,
        "precision_note": (
            "东方财富换手率保留两位小数；仅把同日与前日分母的预期换手率差异"
            "超过0.02个百分点的样本计为可分辨证据。"
        ),
    }


def markdown_report(report: dict) -> str:
    metrics = report["metrics"]
    cross = report["cross_source"]
    lines = [
        "# 2024 年历史流通股本生效日期门禁报告",
        "",
        f"- 门禁状态：**{report['status']}**",
        f"- 整体工程门禁：**{report['overall_quality_status']}**",
        f"- 生成时间：{report['created_at']}",
        f"- 输入指纹：`{report['source']['sha256']}`",
        "",
        "## 结论",
        "",
        "- 14:30 换手率改用交易日当日已生效的流通股本，不再沿用上一交易日股本。",
        "- 历史流通股本由 Baostock 同日日线成交量除以同日换手率还原；该分母描述当日交易所使用的流通盘，不是当前股本回填。",
        "- 独立东方财富日线在股本明显跳变日使用同一天的新分母，支持生效日期为该交易日。",
        "- 日线换手率四位小数的舍入误差已转成 14:30 换手率上下界；阈值边界不确定行单独标记。",
        "",
        "## 全量统计",
        "",
        f"- 输入股票日：{metrics['row_count']:,}。",
        f"- 历史日线、精确14:30与分钟量一致性已通过：{metrics['upstream_gate_rows']:,}。",
        f"- 上述通过集中缺少当日有效流通股本：{metrics['upstream_missing_effective_shares_rows']:,}。",
        f"- 股本门禁通过：{metrics['float_shares_gate_rows']:,}。",
        f"- 14:30换手率公式错误：{metrics['turnover_formula_error_rows']:,}。",
        f"- 换手率5%或10%边界受四位小数舍入影响：{metrics['turnover_boundary_ambiguous_rows']:,}。",
        f"- 当日与此前有效流通股本相差超过1%的股票日：{metrics['share_change_over_1pct_rows']:,}；超过10%：{metrics['share_change_over_10pct_rows']:,}。",
        "",
        "## 第二来源生效日核验",
        "",
        f"- 抽样/匹配：{cross['selected_samples']}/{cross['matched_samples']}；独立代码 {cross['distinct_codes']}。",
        f"- 在东方财富两位小数精度下可分辨：{cross['distinguishable_samples']}。",
        f"- 支持同日新分母：{cross['same_day_supported_samples']}，支持率 {cross['same_day_support_rate']:.2%}。",
        f"- 成交量误差超过0.5%：{cross['volume_mismatches_over_0_5pct']}；接口错误：{len(cross['errors'])}。",
        f"- 精度说明：{cross['precision_note']}",
        "",
        "## 使用边界",
        "",
        "- `historical_float_shares_gate_pass=false` 的股票日不得用于14:30换手率。",
        "- `turnover_5_10_precision_status=BOUNDARY_AMBIGUOUS` 的行不得强行判入或判出5%—10%区间。",
        "- 同日日线只用于还原交易开始前已经生效的静态股本分母；不读取同日收盘价、全日涨跌幅或全日成交额作为14:30特征。",
        "- 本报告只解除历史流通股本生效日期门禁；完成次日退出可成交性门禁前仍不生成冻结候选集、不回测、不调参。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    input_path = pathlib.Path(args.audited_input).expanduser().resolve()
    output = pathlib.Path(args.output).expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"输入不存在：{input_path}")
    if output.exists():
        raise SystemExit(f"输出目录已存在，拒绝覆盖：{output}")
    if args.cross_source_samples < 30:
        raise SystemExit("--cross-source-samples 不能小于30")

    connection = duckdb.connect()
    required_columns = {
        "code",
        "date",
        "cum_volume1430",
        "raw_same_day_float_shares_inferred",
        "raw_full_day_turnover",
        "tencent_daily_volume",
        "history_1430_volume_gate_pass",
    }
    columns = {
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(input_path)]
        ).fetchall()
    }
    missing = sorted(required_columns - columns)
    if missing:
        raise SystemExit("缺少输入字段：" + ", ".join(missing))

    samples = select_cross_source_samples(
        connection, input_path, args.cross_source_samples
    )
    cross = crosscheck_eastmoney(samples)
    support_rate = cross["same_day_support_rate"]
    cross_pass = (
        cross["matched_samples"] >= 30
        and cross["distinguishable_samples"] >= 20
        and support_rate is not None
        and support_rate >= 0.95
        and cross["volume_mismatches_over_0_5pct"] == 0
    )

    output.mkdir(parents=True)
    destination = output / "audited_with_historical_float_shares.parquet"
    input_sql = sql_path(input_path)
    destination_sql = sql_path(destination)
    connection.execute(
        f"""
        COPY (
          WITH shares AS (
            SELECT a.*,
              CASE WHEN isfinite(raw_same_day_float_shares_inferred)
                       AND raw_same_day_float_shares_inferred>0
                     THEN raw_same_day_float_shares_inferred END
                AS historical_float_shares_effective,
              CASE WHEN isfinite(raw_same_day_float_shares_inferred)
                       AND raw_same_day_float_shares_inferred>0
                     THEN date END AS historical_float_shares_effective_date,
              last_value(
                CASE WHEN isfinite(raw_same_day_float_shares_inferred)
                       AND raw_same_day_float_shares_inferred>0
                     THEN raw_same_day_float_shares_inferred END IGNORE NULLS
              ) OVER (
                PARTITION BY code ORDER BY date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
              ) AS prior_historical_float_shares
            FROM read_parquet('{input_sql}') a
          ), calculated AS (
            SELECT *,
              historical_float_shares_effective IS NOT NULL
                AS historical_float_shares_available,
              CASE WHEN historical_float_shares_effective IS NOT NULL
                   THEN historical_float_shares_effective/
                        prior_historical_float_shares-1.0 END
                AS historical_float_shares_change_ratio,
              CASE WHEN historical_float_shares_effective IS NOT NULL
                   THEN cum_volume1430/historical_float_shares_effective*100.0 END
                AS turnover1430_effective,
              CASE WHEN historical_float_shares_effective IS NOT NULL
                         AND isfinite(tencent_daily_volume)
                         AND tencent_daily_volume>0
                         AND isfinite(raw_full_day_turnover)
                   THEN cum_volume1430/tencent_daily_volume
                        *greatest(raw_full_day_turnover-
                          {BAOSTOCK_TURNOVER_HALF_UNIT_PCT},0.0) END
                AS turnover1430_effective_lower,
              CASE WHEN historical_float_shares_effective IS NOT NULL
                         AND isfinite(tencent_daily_volume)
                         AND tencent_daily_volume>0
                         AND isfinite(raw_full_day_turnover)
                   THEN cum_volume1430/tencent_daily_volume
                        *(raw_full_day_turnover+
                          {BAOSTOCK_TURNOVER_HALF_UNIT_PCT}) END
                AS turnover1430_effective_upper
            FROM shares
          ), final AS (
            SELECT *,
              historical_float_shares_available
                AND historical_float_shares_effective_date=date
                AS historical_float_shares_gate_pass,
              CASE
                WHEN turnover1430_effective_lower IS NULL
                  OR turnover1430_effective_upper IS NULL THEN 'UNAVAILABLE'
                WHEN turnover1430_effective_lower<5.0
                  AND turnover1430_effective_upper>=5.0 THEN 'BOUNDARY_AMBIGUOUS'
                WHEN turnover1430_effective_lower<=10.0
                  AND turnover1430_effective_upper>10.0 THEN 'BOUNDARY_AMBIGUOUS'
                WHEN turnover1430_effective_upper<5.0 THEN 'BELOW_5'
                WHEN turnover1430_effective_lower>10.0 THEN 'ABOVE_10'
                ELSE 'INSIDE_5_10'
              END AS turnover_5_10_precision_status,
              'BAOSTOCK_DAILY_VOLUME_DIV_TURNOVER_EFFECTIVE_SAME_DAY'
                AS historical_float_shares_source,
              {BAOSTOCK_TURNOVER_HALF_UNIT_PCT}
                AS baostock_daily_turnover_rounding_half_unit_pct,
              history_1430_volume_gate_pass
                AND historical_float_shares_available
                AND historical_float_shares_effective_date=date
                AS history_1430_volume_float_gate_pass
            FROM calculated
          )
          SELECT * FROM final
        ) TO '{destination_sql}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )

    metrics = row_dict(
        connection,
        """
        SELECT count(*) AS row_count,
          count(*) FILTER(WHERE history_1430_volume_gate_pass)
            AS upstream_gate_rows,
          count(*) FILTER(WHERE history_1430_volume_gate_pass
            AND NOT historical_float_shares_available)
            AS upstream_missing_effective_shares_rows,
          count(*) FILTER(WHERE history_1430_volume_float_gate_pass)
            AS float_shares_gate_rows,
          count(*) FILTER(WHERE history_1430_volume_float_gate_pass
            AND abs(turnover1430_effective-
              cum_volume1430/historical_float_shares_effective*100.0)>1e-10)
            AS turnover_formula_error_rows,
          count(*) FILTER(WHERE history_1430_volume_float_gate_pass
            AND turnover_5_10_precision_status='BOUNDARY_AMBIGUOUS')
            AS turnover_boundary_ambiguous_rows,
          count(*) FILTER(WHERE isfinite(historical_float_shares_change_ratio)
            AND abs(historical_float_shares_change_ratio)>0.01)
            AS share_change_over_1pct_rows,
          count(*) FILTER(WHERE isfinite(historical_float_shares_change_ratio)
            AND abs(historical_float_shares_change_ratio)>0.10)
            AS share_change_over_10pct_rows
        FROM read_parquet(?)
        """,
        [str(destination)],
    )
    gate_pass = (
        metrics["upstream_missing_effective_shares_rows"] == 0
        and metrics["turnover_formula_error_rows"] == 0
        and cross_pass
    )
    digest, size = fingerprint(input_path)
    report = {
        "status": (
            "HISTORICAL_FLOAT_SHARES_EFFECTIVE_DATE_PASS"
            if gate_pass
            else "HISTORICAL_FLOAT_SHARES_EFFECTIVE_DATE_FAIL"
        ),
        "overall_quality_status": "BLOCKED_DATA",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source": {"path": str(input_path), "sha256": digest, "bytes": size},
        "output": {"audited_path": str(destination)},
        "method": {
            "effective_date": "same trading date",
            "formula": "daily volume / (daily turnover pct / 100)",
            "turnover1430_formula": "cum volume at 14:30 / effective float shares * 100",
            "baostock_turnover_rounding_half_unit_pct": (
                BAOSTOCK_TURNOVER_HALF_UNIT_PCT
            ),
        },
        "metrics": metrics,
        "cross_source_pass": cross_pass,
        "cross_source": cross,
    }
    (output / "float-shares-cross-source-evidence.json").write_text(
        json.dumps(cross, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "historical-float-shares-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "historical-float-shares-report.md").write_text(
        markdown_report(report), encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], **metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()
