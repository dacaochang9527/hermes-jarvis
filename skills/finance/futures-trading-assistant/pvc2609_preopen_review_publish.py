#!/usr/bin/env python3
"""Generate, publish, and announce PVC2609 pre-open review/forecast reports."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
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


def latest_night_date(before_or_on: date, lookback_days: int = 10) -> date | None:
    for offset in range(1, lookback_days + 1):
        candidate = before_or_on - timedelta(days=offset)
        try:
            if session_has_bars(candidate, "night"):
                return candidate
        except Exception:
            continue
    return None


def resolve_dates(spec: TargetSpec, target_date: date) -> tuple[date, date]:
    if spec.target == "morning":
        review_date = latest_night_date(target_date)
        if review_date is None:
            raise RuntimeError(f"最近10天未找到可复盘夜盘K线，目标日 {target_date:%Y-%m-%d} 不发布正式报告")
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
    output.write_text(markdown, encoding="utf-8")
    if update_levels:
        generator.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        generator.PREDICTION_LEVELS_PATH.write_text(json.dumps(prediction_payload, ensure_ascii=False, indent=2), encoding="utf-8")
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
    markdown_path.write_text(text, encoding="utf-8")


def publish_report(markdown_path: Path, title: str, dry_run: bool) -> dict:
    if dry_run:
        return {"url": f"DRY-RUN:{markdown_path}", "title": title, "markdown_path": str(markdown_path)}
    command = [sys.executable, str(PUBLISHER), str(markdown_path), "--title", title]
    result = subprocess.run(command, cwd=str(BASE_DIR), text=True, capture_output=True, timeout=360)
    if result.returncode == 0:
        return json.loads(result.stdout)
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


def extract_summary(markdown_path: Path) -> str:
    text = markdown_path.read_text(encoding="utf-8")
    match = re.search(r"## 1\. 一句话结论\n\n(.+?)(?:\n\n##|$)", text, flags=re.DOTALL)
    if not match:
        return "详见飞书文档。"
    summary = re.sub(r"\s+", " ", match.group(1)).strip()
    return summary[:180] + ("..." if len(summary) > 180 else "")


def build_group_message(title: str, url: str, summary: str, local_path: Path, dry_run: bool) -> str:
    prefix = "[DRY-RUN] " if dry_run else ""
    return "\n".join([
        f"{prefix}{title}",
        f"飞书文档：{url}",
        f"摘要：{summary}",
        f"本地文件：{local_path}",
    ])


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
    target_date = args.date or now_cn().date()
    try:
        review_date, next_date = resolve_dates(spec, target_date)
        output = report_path_for(target_date, spec, args.output_dir)
        report_path = generate_report(review_date, next_date, spec, output, update_levels=(not args.dry_run and not args.no_update_levels))
        title = f"PVC2609 {target_date:%Y-%m-%d} {spec.title_session}复盘+预测"
        published = publish_report(report_path, title, dry_run=args.dry_run)
        url = published.get("url") or published.get("document_url") or "URL生成失败"
        print(build_group_message(title, url, extract_summary(report_path), report_path, args.dry_run))
        return 0
    except Exception as exc:
        print(f"PVC2609 {target_date:%Y-%m-%d} {spec.title_session}复盘+预测未发布：{exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
