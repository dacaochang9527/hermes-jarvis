#!/usr/bin/env python3
"""Load the proven PVC2609 implementation as an isolated PVC2701 runtime.

The mature generator/publisher remains the single implementation source.  This
adapter rewrites only contract identifiers in memory and then redirects all
reports/runtime state into this skill directory, so PVC2609 files stay intact.
"""

from __future__ import annotations

import sys
import types
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
