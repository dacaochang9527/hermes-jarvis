#!/usr/bin/env python3
"""Load the proven PVC2609 implementation as an isolated PVC2701 runtime.

The mature generator/publisher remains the single implementation source.  This
adapter rewrites only contract identifiers in memory and then redirects all
reports/runtime state into this skill directory, so PVC2609 files stay intact.
"""

from __future__ import annotations

import sys
import types
import re
from functools import lru_cache
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SKILL_DIR.parent / "futures-trading-assistant"
GENERATOR_TEMPLATE = TEMPLATE_DIR / "pvc2609_generate_session_report.py"
PUBLISHER_TEMPLATE = TEMPLATE_DIR / "pvc2609_preopen_review_publish.py"
INTRADAY_TEMPLATE = TEMPLATE_DIR / "pvc2609_intraday_key_level_report.py"
HEALTHCHECK_TEMPLATE = TEMPLATE_DIR / "pvc2609_automation_healthcheck.py"
DOC_PUBLISHER = TEMPLATE_DIR / "publish_feishu_markdown_doc.py"

REPORT_GROUP_DELIVER = "feishu:oc_d5aa041b453e9b6f8a38fba75fa94b37"
HEALTHCHECK_DELIVER = "feishu:ou_29f43af572af5354dcf63c44af9ca013"
PREOPEN_SCRIPTS = {
    "morning": "pvc2701_morning_review_report.sh",
    "afternoon": "pvc2701_afternoon_review_report.sh",
    "night": "pvc2701_night_review_report.sh",
}
ENABLED_JOBS = {
    "PVC2701期货盘中关键位操作重估": "pvc2701_intraday_key_level_report.sh",
    "PVC2701期货夜盘收盘后次日日盘复盘预测": "pvc2701_morning_review_report.sh",
    "PVC2701期货上午收盘后午盘复盘预测": "pvc2701_afternoon_review_report.sh",
    "PVC2701期货日盘收盘后夜盘复盘预测": "pvc2701_night_review_report.sh",
}
EXPECTED_CRON_EXPR = {
    "PVC2701期货盘中关键位操作重估": "*/3 9-15,21-23 * * 1-5",
    "PVC2701期货夜盘收盘后次日日盘复盘预测": "10 23 * * 1-5",
    "PVC2701期货上午收盘后午盘复盘预测": "40 11 * * 1-5",
    "PVC2701期货日盘收盘后夜盘复盘预测": "10 15 * * 1-5",
}
WRAPPER_SCRIPTS = set(PREOPEN_SCRIPTS.values()) | {
    "pvc2701_intraday_key_level_report.sh",
    "pvc2701_automation_healthcheck.sh",
}


def _price_mentions(value: object) -> list[float]:
    return [float(item) for item in re.findall(r"(?<!\d)(4\d{3})(?!\d)", str(value or ""))]


def _state_handoff_scenarios(path: Path | None) -> dict[str, dict[str, object]]:
    """Read executable anchors from STATE_HANDOFF instead of prose numbers."""
    if path is None or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="ignore")
    handoff_at = text.rfind("STATE_HANDOFF")
    if handoff_at < 0:
        return {}
    handoff = text[handoff_at:]
    scenarios: dict[str, dict[str, object]] = {}
    for match in re.finditer(
        r"(?ms)^  - id:\s*([A-D])\s*$\n(.*?)(?=^  - id:\s*[A-E]\s*$|^monitor_levels_updated:|\Z)",
        handoff,
    ):
        scenario_id, body = match.groups()
        fields: dict[str, str] = {}
        for line in body.splitlines():
            field = re.match(r"^    ([a-z_]+):\s*(.+?)\s*$", line)
            if field:
                fields[field.group(1)] = field.group(2)
        scenarios[scenario_id] = {
            "direction": fields.get("direction"),
            "entry_levels": _price_mentions(fields.get("entry")),
            "invalidation_levels": _price_mentions(fields.get("invalidation")),
        }
    return scenarios


def _bind_generator_integrity(module: types.ModuleType) -> None:
    """Apply PVC2701-only conservative scenario parsing and validation."""
    original_extract = module.extract_prior_scenarios

    def extract_prior_scenarios(path: Path | None) -> list[dict[str, object]]:
        scenarios = original_extract(path)
        handoff = _state_handoff_scenarios(path)
        for scenario in scenarios:
            state = handoff.get(str(scenario.get("scenario_id") or ""))
            if not state:
                continue
            if state.get("direction"):
                scenario["direction"] = state["direction"]
            if state.get("entry_levels"):
                scenario["entry_levels"] = state["entry_levels"]
            if state.get("invalidation_levels"):
                scenario["invalidation_levels"] = state["invalidation_levels"]
        return scenarios

    def evaluate_scenario(scenario: dict[str, object], rows_3m: list[object], summary: dict) -> tuple[str, str, str]:
        """Require a completed-close trigger and chronological confirmation.

        A range touch alone is not a trigger.  Breakdown scenarios must close
        below their anchor; repair scenarios must close above it.  This keeps
        a 4440 intrabar low from falsely satisfying a "close below 4435" plan.
        """
        rows = [row for row in rows_3m if getattr(row, "dt", None) is not None]
        entry_levels = [
            float(value)
            for value in scenario.get("entry_levels", [])
            if module.valid_price(float(value))
        ]
        invalidation_levels = [
            float(value)
            for value in scenario.get("invalidation_levels", [])
            if module.valid_price(float(value))
        ]
        if not rows or not entry_levels:
            return (
                "未触发",
                "前序方案缺少可验证的完成K线或执行锚点，不能事后补写命中",
                "保留为未触发并降级到人工复核",
            )

        direction = str(scenario.get("direction") or "range")
        name = str(scenario.get("name") or "")
        rejection_short = direction == "short" and "承压" in name
        zone_low, zone_high = min(entry_levels), max(entry_levels)
        trigger_index: int | None = None
        confirm_index: int | None = None

        if rejection_short:
            touch_index = next((i for i, row in enumerate(rows) if row.high >= zone_low), None)
            if touch_index is not None:
                trigger_index = touch_index
                confirm_index = next(
                    (i for i in range(touch_index, len(rows)) if rows[i].close < zone_low),
                    None,
                )
        elif direction == "long":
            anchor = zone_low
            trigger_index = next((i for i, row in enumerate(rows) if row.close > anchor), None)
            if trigger_index is not None:
                invalidation = min(invalidation_levels) if invalidation_levels else anchor
                confirm_index = next(
                    (
                        i
                        for i in range(trigger_index + 1, len(rows))
                        if rows[i].low > invalidation and rows[i].close >= anchor
                    ),
                    None,
                )
        else:
            anchor = zone_low
            trigger_index = next((i for i, row in enumerate(rows) if row.close < anchor), None)
            if trigger_index is not None:
                confirm_index = next(
                    (
                        i
                        for i in range(trigger_index + 1, len(rows))
                        if rows[i].high >= anchor - 2 and rows[i].close < anchor
                    ),
                    None,
                )

        if trigger_index is None:
            return (
                "未触发",
                f"没有完成K线满足前序触发锚点 {module.fmt_price(zone_low)}",
                "盘中刺破或触碰不算触发，不做事后归因",
            )
        if confirm_index is None:
            return (
                "部分触发",
                "完成K线到达触发条件，但尚未出现后续回踩/反抽确认",
                "继续等待确认，不把单根K线写成命中",
            )

        after_trigger = rows[trigger_index:]
        invalidated = False
        if invalidation_levels:
            if direction == "long":
                invalidation = min(invalidation_levels)
                invalidated = any(row.close < invalidation for row in after_trigger[1:])
            else:
                invalidation = max(invalidation_levels)
                invalidated = any(row.close > invalidation for row in after_trigger[1:])
        if invalidated:
            return (
                "触发后失败",
                "触发和确认后，完成K线又越过前序失效位",
                "按失效处理，不把盘中一度有利写成最终命中",
            )
        return (
            "触发且确认",
            "完成K线触发后又出现了按时间顺序的回踩/反抽确认",
            "计划有效，执行仍须使用独立止损和目标",
        )

    module.extract_prior_scenarios = extract_prior_scenarios
    module.evaluate_scenario = evaluate_scenario


def _bind_intraday_integrity(module: types.ModuleType, generator: types.ModuleType) -> None:
    """Exclude a Sina bar whose labelled end time is later than quote time."""
    original_parse_quote = generator.parse_quote
    original_session_rows = module.bars_for_intraday_session

    def parse_quote(raw: str) -> dict:
        quote = original_parse_quote(raw)
        module._pvc2701_quote_cutoff = quote.get("quote_dt")
        return quote

    def completed_session_rows(rows: list[object], trading_date: object, session: str) -> list[object]:
        session_rows = original_session_rows(rows, trading_date, session)
        cutoff = getattr(module, "_pvc2701_quote_cutoff", None)
        if cutoff is None:
            cutoff = module.now_cn()
        return [row for row in session_rows if row.dt is None or row.dt <= cutoff]

    generator.parse_quote = parse_quote
    module.bars_for_intraday_session = completed_session_rows
    module.completed_session_rows = completed_session_rows


def _transform(source: str) -> str:
    for old, new in (
        ("PVC2609", "PVC2701"),
        ("V2609", "V2701"),
        ("pvc2609", "pvc2701"),
    ):
        source = source.replace(old, new)
    return source


def _exec_module(name: str, source_path: Path, virtual_file: Path) -> types.ModuleType:
    if not source_path.exists():
        raise RuntimeError(f"母版文件不存在：{source_path}")
    module = types.ModuleType(name)
    module.__file__ = str(virtual_file)
    module.__package__ = ""
    source = _transform(source_path.read_text(encoding="utf-8"))
    sys.modules[name] = module
    try:
        exec(compile(source, str(virtual_file), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


@lru_cache(maxsize=1)
def load_generator() -> types.ModuleType:
    module = _exec_module(
        "pvc2701_generate_session_report_impl",
        GENERATOR_TEMPLATE,
        SKILL_DIR / "pvc2701_generate_session_report.py",
    )
    module.BASE_DIR = SKILL_DIR
    module.REPORTS_DIR = SKILL_DIR / "reports"
    module.RUNTIME_DIR = SKILL_DIR / "runtime" / "pvc2701_feishu_monitor"
    module.EVENT_LOG = module.RUNTIME_DIR / "events.jsonl"
    module.BRIEFING_LOG = module.RUNTIME_DIR / "half_hour_briefings.jsonl"
    module.PREDICTION_LEVELS_PATH = module.RUNTIME_DIR / "latest_prediction_levels.json"
    _bind_generator_integrity(module)
    return module


@lru_cache(maxsize=1)
def load_publisher() -> types.ModuleType:
    generator = load_generator()
    sys.modules["pvc2701_generate_session_report"] = generator
    module = _exec_module(
        "pvc2701_review_publish_impl",
        PUBLISHER_TEMPLATE,
        SKILL_DIR / "pvc2701_review_publish.py",
    )
    module.BASE_DIR = SKILL_DIR
    module.REPORTS_DIR = SKILL_DIR / "reports"
    module.PUBLISHER = DOC_PUBLISHER
    module.generator = generator
    sys.modules["pvc2701_preopen_review_publish"] = module
    return module


def _ensure_template_path() -> None:
    template_dir = str(TEMPLATE_DIR)
    if template_dir not in sys.path:
        sys.path.insert(0, template_dir)


@lru_cache(maxsize=1)
def load_intraday() -> types.ModuleType:
    generator = load_generator()
    publisher = load_publisher()
    sys.modules["pvc2701_generate_session_report"] = generator
    sys.modules["pvc2701_preopen_review_publish"] = publisher
    _ensure_template_path()
    module = _exec_module(
        "pvc2701_intraday_key_level_report_impl",
        INTRADAY_TEMPLATE,
        SKILL_DIR / "pvc2701_intraday_key_level_report.py",
    )
    module.generator = generator
    _bind_intraday_integrity(module, generator)
    sys.modules["pvc2701_intraday_key_level_report"] = module
    return module


def _bind_healthcheck_runtime(module: types.ModuleType) -> None:
    import os
    import py_compile

    module.GROUP_DELIVER = REPORT_GROUP_DELIVER
    module.PREOPEN_SCRIPTS = dict(PREOPEN_SCRIPTS)
    module.ENABLED_JOBS = dict(ENABLED_JOBS)
    module.EXPECTED_CRON_EXPR = dict(EXPECTED_CRON_EXPR)

    def check_python_and_compile() -> str:
        if not module.VENV_PYTHON.exists():
            raise RuntimeError(f"Hermes venv python missing: {module.VENV_PYTHON}")
        files = [
            SKILL_DIR / "pvc2701_adapter.py",
            SKILL_DIR / "pvc2701_generate_session_report.py",
            SKILL_DIR / "pvc2701_review_publish.py",
            SKILL_DIR / "pvc2701_intraday_key_level_report.py",
            SKILL_DIR / "pvc2701_automation_healthcheck.py",
            TEMPLATE_DIR / "publish_feishu_markdown_doc.py",
            INTRADAY_TEMPLATE,
            HEALTHCHECK_TEMPLATE,
        ]
        for path in files:
            if not path.exists():
                raise RuntimeError(f"required python file missing: {path.name}")
            py_compile.compile(str(path), doraise=True)
        return f"compiled {len(files)} python files"

    def check_wrappers() -> str:
        for script in sorted(WRAPPER_SCRIPTS):
            path = module.SCRIPTS_DIR / script
            if not path.exists():
                raise RuntimeError(f"wrapper missing: {path}")
            if not path.is_file():
                raise RuntimeError(f"wrapper is not a file: {path}")
            if not os.access(path, os.X_OK):
                raise RuntimeError(f"wrapper is not executable: {path}")
            text = path.read_text(encoding="utf-8", errors="replace")
            if "pvc2701-review-forecast" not in text:
                raise RuntimeError(f"wrapper does not target pvc2701 skill: {path.name}")
        return f"checked {len(WRAPPER_SCRIPTS)} wrappers"

    def check_cron_config() -> str:
        jobs = module.load_jobs()
        by_name = {str(job.get("name")): job for job in jobs}
        for name, script in ENABLED_JOBS.items():
            job = by_name.get(name)
            if not job:
                raise RuntimeError(f"enabled futures job missing: {name}")
            if job.get("enabled") is not True:
                raise RuntimeError(f"futures job is not enabled: {name}")
            if job.get("script") != script:
                raise RuntimeError(f"{name} script mismatch: {job.get('script')} != {script}")
            if job.get("deliver") != REPORT_GROUP_DELIVER:
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
            if str(job.get("name", "")).startswith("PVC2701")
            and "pvc2701-review-forecast" in str(job.get("workdir", ""))
            and job.get("enabled") is False
        ]
        if disabled:
            raise RuntimeError(f"disabled PVC2701 jobs still present: {', '.join(map(str, disabled))}")

        healthcheck_name = "PVC2701期货自动化预检"
        healthcheck_job = by_name.get(healthcheck_name)
        if not healthcheck_job:
            raise RuntimeError(f"enabled futures job missing: {healthcheck_name}")
        if healthcheck_job.get("enabled") is not True:
            raise RuntimeError(f"futures job is not enabled: {healthcheck_name}")
        if healthcheck_job.get("script") != "pvc2701_automation_healthcheck.sh":
            raise RuntimeError(
                f"{healthcheck_name} script mismatch: {healthcheck_job.get('script')} != pvc2701_automation_healthcheck.sh"
            )
        if healthcheck_job.get("deliver") != HEALTHCHECK_DELIVER:
            raise RuntimeError(f"{healthcheck_name} deliver mismatch: {healthcheck_job.get('deliver')}")
        healthcheck_expr = (healthcheck_job.get("schedule") or {}).get("expr")
        if healthcheck_expr != "5,35 11,15,23 * * 1-5":
            raise RuntimeError(f"{healthcheck_name} schedule mismatch: {healthcheck_expr}")

        timeout = module.config_timeout_seconds()
        if timeout is None or timeout < 360:
            raise RuntimeError(f"cron.script_timeout_seconds should be >= 360, current={timeout}")
        return f"checked {len(ENABLED_JOBS)} enabled jobs, timeout={timeout}s"

    module.check_python_and_compile = check_python_and_compile
    module.check_wrappers = check_wrappers
    module.check_cron_config = check_cron_config


@lru_cache(maxsize=1)
def load_healthcheck() -> types.ModuleType:
    generator = load_generator()
    publisher = load_publisher()
    intraday = load_intraday()
    sys.modules["pvc2701_generate_session_report"] = generator
    sys.modules["pvc2701_preopen_review_publish"] = publisher
    sys.modules["pvc2701_intraday_key_level_report"] = intraday
    _ensure_template_path()
    module = _exec_module(
        "pvc2701_automation_healthcheck_impl",
        HEALTHCHECK_TEMPLATE,
        SKILL_DIR / "pvc2701_automation_healthcheck.py",
    )
    module.generator = generator
    module.preopen = publisher
    module.intraday = intraday
    _bind_healthcheck_runtime(module)
    return module
