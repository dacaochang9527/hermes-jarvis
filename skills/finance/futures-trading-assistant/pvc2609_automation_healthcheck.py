#!/usr/bin/env python3
"""Pre-flight checks for PVC2609 futures automations.

Cron usage is intentionally quiet: print nothing when everything passes, so
Hermes no-agent delivery stays silent. Print a concise alert only when a check
fails, giving the user time to fix the issue before the real scheduled task.
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import traceback
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pvc2609_generate_session_report as generator
import pvc2609_intraday_key_level_report as intraday
import pvc2609_preopen_review_publish as preopen
import publish_feishu_markdown_doc as feishu_publisher

BASE_DIR = Path(__file__).resolve().parent
HERMES_HOME = Path.home() / ".hermes"
SCRIPTS_DIR = HERMES_HOME / "scripts"
JOBS_PATH = HERMES_HOME / "cron" / "jobs.json"
CONFIG_PATH = HERMES_HOME / "config.yaml"
VENV_PYTHON = HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python"
RUNTIME_DIR = BASE_DIR / "runtime" / "pvc2609_feishu_monitor"
HEALTH_DIR = RUNTIME_DIR / "healthcheck"
LOG_PATH = RUNTIME_DIR / "automation_healthcheck.jsonl"
TZ = ZoneInfo("Asia/Shanghai")

GROUP_DELIVER = "feishu:oc_3b94cfb91274b70374954d7b12f12432"
TARGET_BY_HOUR_MINUTE = {
    (11, 35): "afternoon",
    (15, 5): "night",
    (23, 5): "morning",
}
TARGET_LABELS = {"morning": "夜盘收盘后次日日盘", "afternoon": "上午收盘后午盘", "night": "日盘收盘后夜盘"}
PREOPEN_SCRIPTS = {
    "morning": "pvc2609_morning_preopen_report.sh",
    "afternoon": "pvc2609_afternoon_preopen_report.sh",
    "night": "pvc2609_night_preopen_report.sh",
}
ENABLED_JOBS = {
    "PVC2609期货盘中关键位操作重估": "pvc2609_intraday_key_level_report.sh",
    "PVC2609期货夜盘收盘后次日日盘复盘预测": "pvc2609_morning_preopen_report.sh",
    "PVC2609期货上午收盘后午盘复盘预测": "pvc2609_afternoon_preopen_report.sh",
    "PVC2609期货日盘收盘后夜盘复盘预测": "pvc2609_night_preopen_report.sh",
}

EXPECTED_CRON_EXPR = {
    "PVC2609期货盘中关键位操作重估": "*/3 9-15,21-23 * * 1-5",
    "PVC2609期货夜盘收盘后次日日盘复盘预测": "10 23 * * 1-5",
    "PVC2609期货上午收盘后午盘复盘预测": "40 11 * * 1-5",
    "PVC2609期货日盘收盘后夜盘复盘预测": "10 15 * * 1-5",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def now_cn() -> datetime:
    return datetime.now(TZ)


def parse_yyyymmdd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def select_target() -> str:
    current = now_cn()
    return TARGET_BY_HOUR_MINUTE.get((current.hour, current.minute), "skip")


def run_check(name: str, fn) -> CheckResult:
    try:
        detail = fn() or "OK"
        return CheckResult(name=name, ok=True, detail=str(detail))
    except Exception as exc:
        return CheckResult(name=name, ok=False, detail=f"{exc}\n{traceback.format_exc(limit=3)}")


def load_jobs() -> list[dict]:
    if not JOBS_PATH.exists():
        raise RuntimeError(f"cron jobs file missing: {JOBS_PATH}")
    data = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("cron jobs file has no jobs list")
    return jobs


def check_python_and_compile() -> str:
    if not VENV_PYTHON.exists():
        raise RuntimeError(f"Hermes venv python missing: {VENV_PYTHON}")
    files = [
        BASE_DIR / "pvc2609_generate_session_report.py",
        BASE_DIR / "pvc2609_preopen_review_publish.py",
        BASE_DIR / "pvc2609_intraday_key_level_report.py",
        BASE_DIR / "pvc2609_automation_healthcheck.py",
        BASE_DIR / "publish_feishu_markdown_doc.py",
    ]
    for path in files:
        if not path.exists():
            raise RuntimeError(f"required python file missing: {path.name}")
        py_compile.compile(str(path), doraise=True)
    return f"compiled {len(files)} python files"


def check_wrappers() -> str:
    scripts = set(PREOPEN_SCRIPTS.values()) | {
        "pvc2609_intraday_key_level_report.sh",
        "pvc2609_automation_healthcheck.sh",
    }
    for script in sorted(scripts):
        path = SCRIPTS_DIR / script
        if not path.exists():
            raise RuntimeError(f"wrapper missing: {path}")
        if not path.is_file():
            raise RuntimeError(f"wrapper is not a file: {path}")
        if not os.access(path, os.X_OK):
            raise RuntimeError(f"wrapper is not executable: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if script.startswith("pvc2609_") and "futures-trading-assistant" not in text:
            raise RuntimeError(f"wrapper does not cd into futures assistant: {path.name}")
    return f"checked {len(scripts)} wrappers"


def config_timeout_seconds() -> int | None:
    if not CONFIG_PATH.exists():
        return None
    text = CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"script_timeout_seconds:\s*(\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def check_cron_config() -> str:
    jobs = load_jobs()
    by_name = {str(job.get("name")): job for job in jobs}
    for name, script in ENABLED_JOBS.items():
        job = by_name.get(name)
        if not job:
            raise RuntimeError(f"enabled futures job missing: {name}")
        if job.get("enabled") is not True:
            raise RuntimeError(f"futures job is not enabled: {name}")
        if job.get("script") != script:
            raise RuntimeError(f"{name} script mismatch: {job.get('script')} != {script}")
        if job.get("deliver") != GROUP_DELIVER:
            raise RuntimeError(f"{name} deliver mismatch: {job.get('deliver')}")
        expr = (job.get("schedule") or {}).get("expr")
        if not expr:
            raise RuntimeError(f"{name} schedule missing")
        expected_expr = EXPECTED_CRON_EXPR.get(name)
        if expected_expr and expr != expected_expr:
            raise RuntimeError(f"{name} schedule mismatch: {expr} != {expected_expr}")

    disabled = [
        job.get("name")
        for job in jobs
        if (("期货" in str(job.get("name", ""))) or ("futures-trading-assistant" in str(job.get("workdir", ""))))
        and job.get("enabled") is False
    ]
    if disabled:
        raise RuntimeError(f"disabled futures jobs still present: {', '.join(map(str, disabled))}")

    timeout = config_timeout_seconds()
    if timeout is None or timeout < 360:
        raise RuntimeError(f"cron.script_timeout_seconds should be >= 360, current={timeout}")
    return f"checked {len(ENABLED_JOBS)} enabled jobs, timeout={timeout}s"


def check_prediction_levels() -> str:
    path = generator.PREDICTION_LEVELS_PATH
    if not path.exists():
        raise RuntimeError(f"latest prediction levels missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    levels = data.get("levels")
    if not isinstance(levels, list) or not levels:
        raise RuntimeError("latest prediction levels has no usable levels")
    usable = [item for item in levels if isinstance(item, dict) and item.get("price") and item.get("role")]
    if not usable:
        raise RuntimeError("latest prediction levels has no price/role entries")
    return f"levels={len(usable)}, source={data.get('source_doc')}"


def check_market_data() -> str:
    quote = generator.parse_quote(generator.fetch_text(generator.QUOTE_URL))
    rows_3m = generator.fetch_klines(3)
    rows_15m = generator.fetch_klines(15)
    daily = generator.fetch_daily()
    if not rows_3m:
        raise RuntimeError("3m K-line source returned no rows")
    if not rows_15m:
        raise RuntimeError("15m K-line source returned no rows")
    if not daily:
        raise RuntimeError("daily K-line source returned no rows")
    return f"quote={quote['last']:.0f}@{quote['quote_dt'].strftime('%Y-%m-%d %H:%M')}, 3m={len(rows_3m)}, 15m={len(rows_15m)}, daily={len(daily)}"


def check_feishu_token_and_convert() -> str:
    feishu_publisher.load_env()
    token = feishu_publisher.get_tenant_token()
    converted = feishu_publisher.api_request(
        "POST",
        "/open-apis/docx/v1/documents/blocks/convert",
        token,
        json={"content_type": "markdown", "content": "# PVC2609 自动化预检\n\n- markdown convert ok"},
        timeout=30,
    )
    data = converted.get("data") or {}
    blocks = data.get("blocks") or []
    if not blocks:
        raise RuntimeError("Feishu markdown converter returned no blocks")
    return f"tenant token ok, markdown blocks={len(blocks)}"


def check_feishu_markdown_convertible(markdown_path: Path) -> str:
    markdown = markdown_path.read_text(encoding="utf-8")
    feishu_publisher.load_env()
    token = feishu_publisher.get_tenant_token()
    converted = feishu_publisher.api_request(
        "POST",
        "/open-apis/docx/v1/documents/blocks/convert",
        token,
        json={"content_type": "markdown", "content": markdown},
        timeout=60,
    )
    data = converted.get("data") or {}
    blocks = data.get("blocks") or []
    if not blocks:
        raise RuntimeError(f"Feishu converter returned no blocks for {markdown_path.name}")
    max_blocks = 950
    if len(blocks) <= max_blocks:
        return f"blocks={len(blocks)}"

    slim_path = preopen.trim_for_feishu(markdown_path)
    slim_markdown = slim_path.read_text(encoding="utf-8")
    slim_converted = feishu_publisher.api_request(
        "POST",
        "/open-apis/docx/v1/documents/blocks/convert",
        token,
        json={"content_type": "markdown", "content": slim_markdown},
        timeout=60,
    )
    slim_blocks = (slim_converted.get("data") or {}).get("blocks") or []
    if not slim_blocks:
        raise RuntimeError(f"Feishu converter returned no blocks for slim report {slim_path.name}")
    if len(slim_blocks) > max_blocks:
        raise RuntimeError(f"Feishu block limit exceeded after slim fallback: {len(slim_blocks)} > {max_blocks}")
    return f"canonical blocks={len(blocks)}, slim fallback blocks={len(slim_blocks)}"


def preopen_dry_run(target: str, target_date: date) -> str:
    spec = preopen.TARGETS[target]
    review_date, next_date = preopen.resolve_dates(spec, target_date)
    output_dir = HEALTH_DIR / "preopen" / target
    output = preopen.report_path_for(target_date, spec, output_dir)
    report_path = preopen.generate_report(review_date, next_date, spec, output, update_levels=False)
    text = report_path.read_text(encoding="utf-8")
    required_markers = ["## 1. 一句话结论", "情景概率", "方案 A", "执行纪律", "STATE_HANDOFF"]
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise RuntimeError(f"dry-run report missing markers: {', '.join(missing)}")
    convert_detail = check_feishu_markdown_convertible(report_path)
    published = preopen.publish_report(report_path, f"PVC2609 {target_date:%Y-%m-%d} {spec.title_session}预检", dry_run=True)
    if not str(published.get("url", "")).startswith("DRY-RUN:"):
        raise RuntimeError("preopen dry-run publish did not stay in dry-run mode")
    return f"{TARGET_LABELS[target]} dry-run ok: {report_path.name}, Feishu convert {convert_detail}"


def check_intraday_dry_run(target_date: date) -> str:
    quote = generator.parse_quote(generator.fetch_text(generator.QUOTE_URL))
    rows_3m = generator.fetch_klines(3)
    rows_15m = generator.fetch_klines(15)
    rows_30m = generator.fetch_klines(30)
    if len(rows_3m) < 2:
        raise RuntimeError("not enough 3m bars for intraday dry-run")
    levels, source_doc = intraday.load_key_levels()
    force_level = levels[0].price if levels else quote["last"]
    trigger = intraday.find_trigger(levels, rows_3m[-2:], force_level=force_level)
    if trigger is None:
        raise RuntimeError("forced intraday trigger was not created")
    new_levels = intraday.compute_new_levels(trigger, quote, rows_3m[-20:], rows_15m)
    if not new_levels:
        raise RuntimeError("intraday new levels were not generated")
    generated_at = now_cn()
    report_name = f"pvc2609_{target_date:%Y%m%d}_intraday_healthcheck.md"
    markdown = intraday.build_markdown(
        trading_date=target_date,
        session="morning",
        trigger=trigger,
        quote=quote,
        source_doc=source_doc,
        session_rows=rows_3m[-20:],
        rows_15m=rows_15m,
        rows_30m=rows_30m,
        new_levels=new_levels,
        generated_at=generated_at,
        report_name=report_name,
        report_count=1,
    )
    if "STATE_HANDOFF" not in markdown or "## 3. 操作概率表" not in markdown:
        raise RuntimeError("intraday dry-run markdown missing required sections")
    output_dir = HEALTH_DIR / "intraday"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / report_name
    report_path.write_text(markdown, encoding="utf-8")
    convert_detail = check_feishu_markdown_convertible(report_path)
    published = preopen.publish_report(report_path, f"PVC2609 {target_date:%Y-%m-%d} 盘中关键位预检", dry_run=True)
    if not str(published.get("url", "")).startswith("DRY-RUN:"):
        raise RuntimeError("intraday dry-run publish did not stay in dry-run mode")
    return f"intraday dry-run ok: {report_path.name}, Feishu convert {convert_detail}"


def append_log(payload: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_alert(target: str, target_date: date, failures: list[CheckResult], results: list[CheckResult]) -> str:
    target_label = TARGET_LABELS.get(target, "全量")
    lines = [
        f"PVC2609 自动化预检失败（{target_date:%Y-%m-%d} {target_label}）",
        "正式任务尚未执行，请先处理以下问题：",
        "",
    ]
    for idx, failure in enumerate(failures, 1):
        detail = failure.detail.strip().splitlines()[0]
        lines.append(f"{idx}. {failure.name}: {detail}")
    lines.extend([
        "",
        "已通过：",
        "、".join(result.name for result in results if result.ok) or "无",
        "",
        f"日志：{LOG_PATH}",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PVC2609 automation pre-flight healthcheck.")
    parser.add_argument("--target", choices=("auto", "all", "morning", "afternoon", "night"), default="auto")
    parser.add_argument("--date", type=parse_yyyymmdd, help="target date, defaults to today")
    parser.add_argument("--verbose", action="store_true", help="print success summary too")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = args.date or now_cn().date()
    target = select_target() if args.target == "auto" else args.target
    if target == "skip":
        append_log({
            "ts": now_cn().isoformat(),
            "target": target,
            "target_date": target_date.isoformat(),
            "ok": True,
            "results": [],
            "skipped": "outside pre-flight windows",
        })
        if args.verbose:
            print(f"PVC2609 自动化预检跳过：当前不在 11:35/15:05/23:05 预检窗口（{now_cn().strftime('%H:%M')}）。")
        return 0
    targets = list(preopen.TARGETS) if target == "all" else [target]

    results: list[CheckResult] = [
        run_check("Python语法/依赖", check_python_and_compile),
        run_check("wrapper脚本", check_wrappers),
        run_check("cron配置", check_cron_config),
        run_check("最新关键位文件", check_prediction_levels),
        run_check("行情数据源", check_market_data),
        run_check("飞书token/Markdown转换", check_feishu_token_and_convert),
    ]
    for item in targets:
        results.append(run_check(f"{TARGET_LABELS[item]}报告dry-run", lambda item=item: preopen_dry_run(item, target_date)))
    results.append(run_check("盘中关键位dry-run", lambda: check_intraday_dry_run(target_date)))

    failures = [result for result in results if not result.ok]
    append_log({
        "ts": now_cn().isoformat(),
        "target": target,
        "target_date": target_date.isoformat(),
        "ok": not failures,
        "results": [result.__dict__ for result in results],
    })

    if failures:
        print(build_alert(target, target_date, failures, results))
    elif args.verbose:
        passed = "、".join(result.name for result in results)
        print(f"PVC2609 自动化预检通过（{target_date:%Y-%m-%d}，target={target}）：{passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
