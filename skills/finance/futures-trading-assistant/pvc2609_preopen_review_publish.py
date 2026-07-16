#!/usr/bin/env python3
"""Generate, publish, and announce PVC2609 pre-open review/forecast reports."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pvc2609_generate_session_report as generator

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
PUBLISHER = BASE_DIR / "publish_feishu_markdown_doc.py"
TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class TargetSpec:
    target: str
    review_session: str
    next_session: str
    filename_suffix: str
    title_session: str


TARGETS = {
    "morning": TargetSpec("morning", "night", "morning", "morning_preopen_review_forecast", "日盘开盘前"),
    "afternoon": TargetSpec("afternoon", "morning", "afternoon", "afternoon_preopen_review_forecast", "午盘开盘前"),
    "night": TargetSpec("night", "day", "night", "night_preopen_review_forecast", "夜盘开盘前"),
}


def now_cn() -> datetime:
    return datetime.now(TZ)


def parse_yyyymmdd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def format_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def report_path_for(target_date: date, spec: TargetSpec, output_dir: Path | None) -> Path:
    base = output_dir or REPORTS_DIR
    return base / f"pvc2609_{target_date:%Y%m%d}_{spec.filename_suffix}.md"


def session_has_bars(trading_date: date, session: str) -> bool:
    rows = generator.fetch_klines(3)
    return bool(generator.bars_for_session(rows, trading_date, session))


def latest_night_date(before_or_on: date, lookback_days: int = 10, include_same_day: bool = False) -> date | None:
    start_offset = 0 if include_same_day else 1
    for offset in range(start_offset, lookback_days + 1):
        candidate = before_or_on - timedelta(days=offset)
        try:
            if session_has_bars(candidate, "night"):
                return candidate
        except Exception:
            continue
    return None


def next_day_after_available_night(after_date: date, lookahead_days: int = 10) -> date:
    rows = generator.fetch_klines(3)
    for offset in range(1, lookahead_days + 1):
        candidate = after_date + timedelta(days=offset)
        if generator.bars_for_session(rows, candidate, "day"):
            return candidate
    for offset in range(1, lookahead_days + 1):
        candidate = after_date + timedelta(days=offset)
        if candidate.weekday() < 5:
            return candidate
    return after_date + timedelta(days=1)


def next_weekday(after_date: date) -> date:
    for offset in range(1, 8):
        candidate = after_date + timedelta(days=offset)
        if candidate.weekday() < 5:
            return candidate
    return after_date + timedelta(days=1)


def default_target_date(spec: TargetSpec, current: datetime | None = None) -> date:
    current = current or now_cn()
    today = current.date()
    if spec.target != "morning":
        return today
    if (current.hour, current.minute) >= (23, 5):
        return next_weekday(today)
    review_date = latest_night_date(today, include_same_day=True)
    if review_date is not None:
        return next_day_after_available_night(review_date)
    return today


def resolve_dates(spec: TargetSpec, target_date: date) -> tuple[date, date]:
    if spec.target == "morning":
        review_date = latest_night_date(target_date)
        if review_date is None:
            raise RuntimeError(f"最近10天未找到可复盘夜盘K线，目标日 {target_date:%Y-%m-%d} 不发布正式报告")
        expected_target = next_day_after_available_night(review_date)
        if expected_target != target_date:
            raise RuntimeError(
                f"最近可用夜盘是 {review_date:%Y-%m-%d}，其下一日盘应为 {expected_target:%Y-%m-%d}；"
                f"目标日 {target_date:%Y-%m-%d} 缺少前一夜盘K线，不发布正式报告"
            )
        return review_date, target_date
    return target_date, target_date


def make_generator_args(review_date: date, next_date: date, spec: TargetSpec, output: Path, update_levels: bool) -> argparse.Namespace:
    return argparse.Namespace(
        date=review_date,
        session=spec.review_session,
        next_session=spec.next_session,
        next_date=next_date,
        output=output,
        overwrite=True,
        update_levels=update_levels,
    )


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def validate_report_bundle(
    markdown: str,
    prediction_payload: dict,
    review_date: date,
    spec: TargetSpec,
    prior_report: Path | None,
) -> None:
    errors: list[str] = []
    quality = prediction_payload.get("_quality") or {}
    try:
        quote_dt = datetime.fromisoformat(str(quality.get("quote_dt")))
    except (TypeError, ValueError):
        quote_dt = None
    if quote_dt is None or quote_dt.date() != review_date:
        errors.append(f"quote 日期不匹配：{quality.get('quote_dt')} != {review_date}")
    if spec.review_session == "day" and quality.get("daily_date") != review_date.isoformat():
        errors.append(f"日K未包含复盘日：{quality.get('daily_date')} != {review_date}")
    if prior_report is None:
        errors.append("未找到治理当前时段的前序正式计划")
    for placeholder in ("前序计划：`未找到`", "price: TBD", "需人工复核后作为正式交易文档"):
        if placeholder in markdown:
            errors.append(f"正式报告仍含占位内容：{placeholder}")

    session = quality.get("session") or {}
    plan = quality.get("plan") or {}
    try:
        session_range = max(float(session["high"]) - float(session["low"]), 1.0)
        close_location = (float(session["close"]) - float(session["low"])) / session_range
        rejection = float(session["high"]) - float(session["close"])
        if close_location <= 0.15 and rejection >= max(20.0, session_range * 0.35) and quality.get("bias") == "range":
            errors.append("收盘贴近低点且明显冲高回落，却被判定为区间震荡")
        near_distance = float(plan["pressure_low"]) - float(session["close"])
        if near_distance > float(plan["near_distance_limit"]) + 0.01:
            errors.append(f"近端压力距收盘 {near_distance:.0f} 点，超过动态上限 {float(plan['near_distance_limit']):.0f} 点")
        if not (
            float(plan["pressure_low"]) <= float(plan["pressure_high"])
            < float(plan["core_pressure_low"]) <= float(plan["core_pressure_high"])
            < float(plan["far_pressure_low"]) <= float(plan["far_pressure_high"])
        ):
            errors.append("近端、核心、远端压力层级顺序异常")
        if float(plan["support"]) == float(plan["low"]):
            errors.append("近端支撑与本阶段低点重复，关键位角色未分层")
    except (KeyError, TypeError, ValueError):
        errors.append("质量上下文缺少完整的时段或关键位数据")

    scenarios = quality.get("scenarios") or []
    scenario_ids = [item.get("scenario_id") for item in scenarios]
    if scenario_ids != ["A", "B", "C", "D", "E"]:
        errors.append(f"方案编号异常：{scenario_ids}")
    for item in scenarios:
        direction = item.get("direction")
        if direction not in ("short", "long"):
            continue
        try:
            entry_low = float(item["entry_low"])
            entry_high = float(item["entry_high"])
            stop = float(item["stop_anchor"])
            target1 = float(item["target1_anchor"])
            target2 = float(item["target2_anchor"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"方案 {item.get('scenario_id')} 缺少数值化入场、止损或目标")
            continue
        if direction == "short" and not (stop >= entry_high and target1 < entry_low and target2 < target1):
            errors.append(f"空单方案 {item.get('scenario_id')} 的止损/止盈方向错误")
        if direction == "long" and not (stop < entry_low and target1 > entry_high and target2 > target1):
            errors.append(f"多单方案 {item.get('scenario_id')} 的止损/止盈方向错误")
    for number, scenario_id in ((13, "A"), (14, "B"), (15, "C"), (16, "D")):
        if not re.search(rf"##\s*{number}\..*方案\s*{scenario_id}", markdown):
            errors.append(f"详细方案章节缺失或编号错位：{scenario_id}")
    monitor_prices = [item.get("price") for item in prediction_payload.get("levels", [])]
    if len(monitor_prices) != len(set(monitor_prices)):
        errors.append(f"监控关键位存在重复价格：{monitor_prices}")
    if errors:
        raise RuntimeError("报告质量门禁失败：" + "；".join(errors))


def generate_report(review_date: date, next_date: date, spec: TargetSpec, output: Path, update_levels: bool) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    quote = generator.parse_quote(generator.fetch_text(generator.QUOTE_URL))
    klines = {minutes: generator.fetch_klines(minutes) for minutes in generator.MINUTE_PERIODS}
    daily = generator.fetch_daily()
    if not generator.bars_for_session(klines.get(3, []), review_date, spec.review_session):
        raise RuntimeError(f"{review_date:%Y-%m-%d} {generator.session_title(spec.review_session)} 3m K线不足，不发布正式报告")
    args = make_generator_args(review_date, next_date, spec, output, update_levels)
    prior_report = generator.find_prior_report(review_date, spec.review_session)
    markdown, prediction_payload = generator.build_report(args, quote, klines, daily, prior_report)
    validate_report_bundle(markdown, prediction_payload, review_date, spec, prior_report)
    atomic_write_text(output, markdown)
    if update_levels:
        generator.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            generator.PREDICTION_LEVELS_PATH,
            json.dumps(generator.runtime_prediction_payload(prediction_payload), ensure_ascii=False, indent=2),
        )
    return output


def trim_for_feishu(markdown_path: Path) -> Path:
    text = markdown_path.read_text(encoding="utf-8")
    slim = re.sub(r"\n```text\nSTATE_HANDOFF\n.*?\n```\n", "\n", text, flags=re.DOTALL)
    slim = re.sub(r"\n## 18\. 小资金点数现实与风险可行性\n.*?(?=\n## 19\.)", "\n", slim, flags=re.DOTALL)
    slim_path = markdown_path.with_name(f"{markdown_path.stem}.slim_feishu{markdown_path.suffix}")
    slim_path.write_text(slim, encoding="utf-8")
    return slim_path


def patch_canonical_link(markdown_path: Path, url: str) -> None:
    text = markdown_path.read_text(encoding="utf-8")
    line = f"> 飞书在线文档：{url}  "
    if re.search(r"^> 飞书在线文档：.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^> 飞书在线文档：.*$", line, text, count=1, flags=re.MULTILINE)
    else:
        text = re.sub(r"(^> 生成时间：.*$)", rf"\1\n{line}", text, count=1, flags=re.MULTILINE)
    atomic_write_text(markdown_path, text)


def extract_existing_url(markdown_path: Path) -> str | None:
    if not markdown_path.exists():
        return None
    match = re.search(r"^> 飞书在线文档：(https?://\S+)", markdown_path.read_text(encoding="utf-8", errors="ignore"), flags=re.MULTILINE)
    return match.group(1) if match else None


def publish_report(markdown_path: Path, title: str, dry_run: bool) -> dict:
    if dry_run:
        return {"url": f"DRY-RUN:{markdown_path}", "title": title, "markdown_path": str(markdown_path)}
    command = [sys.executable, str(PUBLISHER), str(markdown_path), "--title", title]
    result = subprocess.run(command, cwd=str(BASE_DIR), text=True, capture_output=True, timeout=360)
    if result.returncode == 0:
        payload = json.loads(result.stdout)
        url = payload.get("url") or payload.get("document_url")
        if url:
            patch_canonical_link(markdown_path, url)
        return payload
    error_text = result.stderr or result.stdout
    if "max:" not in error_text and "blocks" not in error_text:
        raise RuntimeError(error_text.strip() or "飞书文档发布失败")
    slim_path = trim_for_feishu(markdown_path)
    slim_result = subprocess.run([sys.executable, str(PUBLISHER), str(slim_path), "--title", title], cwd=str(BASE_DIR), text=True, capture_output=True, timeout=360)
    if slim_result.returncode != 0:
        raise RuntimeError((slim_result.stderr or slim_result.stdout).strip() or "飞书精简版文档发布失败")
    payload = json.loads(slim_result.stdout)
    url = payload.get("url")
    if url:
        patch_canonical_link(markdown_path, url)
    payload["canonical_markdown_path"] = str(markdown_path)
    payload["slim_markdown_path"] = str(slim_path)
    return payload


def validate_level_sanity(markdown_path: Path) -> None:
    """Block publishing if auto-generated near resistance is clearly stale/far.

    This guard prevents repeating the 2026-06-29 morning failure where a daily/far
    resistance band was promoted into the next-session near-term pressure zone.
    """
    text = markdown_path.read_text(encoding="utf-8")
    summary_match = re.search(
        r"K线开盘 / 最高 / 最低 / 收盘 \|\s*([0-9.]+)\s*/\s*([0-9.]+)\s*/\s*([0-9.]+)\s*/\s*([0-9.]+)",
        text,
    )
    pressure_match = re.search(r"\| 近端压力 \|\s*([0-9]+)(?:-([0-9]+))?\s*\|", text)
    if not summary_match or not pressure_match:
        return
    session_high = float(summary_match.group(2))
    session_low = float(summary_match.group(3))
    session_close = float(summary_match.group(4))
    pressure_low = float(pressure_match.group(1))
    distance_limit = min(50.0, max(20.0, (session_high - session_low) * 0.35))
    if pressure_low - session_close > distance_limit:
        raise RuntimeError(
            f"关键位 sanity check failed：近端压力 {pressure_low:.0f} 距收盘 {session_close:.0f} 超过动态上限 {distance_limit:.0f} 点，"
            "疑似把远端压力误作近端压力，已阻止自动发布"
        )


def extract_summary(markdown_path: Path) -> str:
    text = markdown_path.read_text(encoding="utf-8")
    match = re.search(r"## 1\. 一句话结论\n\n(.+?)(?:\n\n##|$)", text, flags=re.DOTALL)
    if not match:
        return "详见飞书文档。"
    summary = re.sub(r"\s+", " ", match.group(1)).strip()
    return summary[:180] + ("..." if len(summary) > 180 else "")


def build_group_message(title: str, url: str, summary: str, local_path: Path, dry_run: bool, previous_url: str | None = None) -> str:
    prefix = "[DRY-RUN] " if dry_run else ""
    lines = []
    if previous_url and not dry_run:
        lines.extend([
            "更正：此前同一时段报告因自动生成质量门禁缺失，现由通过校验的新版本取代。",
            f"旧文档保留追溯：{previous_url}",
        ])
    lines.extend([
        f"{prefix}{title}",
        f"飞书文档：{url}",
        f"摘要：{summary}",
        f"本地文件：{local_path}",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and publish PVC2609 pre-open review/forecast.")
    parser.add_argument("--target", required=True, choices=tuple(TARGETS), help="pre-open report target")
    parser.add_argument("--date", type=parse_yyyymmdd, help="target session date, defaults to today in Asia/Shanghai")
    parser.add_argument("--output-dir", type=Path, help="override report output directory, useful for dry-run tests")
    parser.add_argument("--dry-run", action="store_true", help="generate report and print preview without publishing to Feishu")
    parser.add_argument("--no-update-levels", action="store_true", help="do not update runtime latest_prediction_levels.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec = TARGETS[args.target]
    target_date = args.date or default_target_date(spec)
    try:
        review_date, next_date = resolve_dates(spec, target_date)
        output = report_path_for(target_date, spec, args.output_dir)
        previous_url = extract_existing_url(output)
        report_path = generate_report(review_date, next_date, spec, output, update_levels=(not args.dry_run and not args.no_update_levels))
        validate_level_sanity(report_path)
        title = f"PVC2609 {target_date:%Y-%m-%d} {spec.title_session}复盘+预测" + ("（更正版）" if previous_url and not args.dry_run else "")
        published = publish_report(report_path, title, dry_run=args.dry_run)
        url = published.get("url") or published.get("document_url") or "URL生成失败"
        if not args.dry_run and not str(url).startswith("http"):
            raise RuntimeError("飞书文档发布未返回有效 URL")
        print(build_group_message(title, url, extract_summary(report_path), report_path, args.dry_run, previous_url))
        return 0
    except Exception as exc:
        print(f"PVC2609 {target_date:%Y-%m-%d} {spec.title_session}复盘+预测未发布：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
