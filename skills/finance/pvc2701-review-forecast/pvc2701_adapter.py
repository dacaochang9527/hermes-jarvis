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
DOC_PUBLISHER = TEMPLATE_DIR / "publish_feishu_markdown_doc.py"


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
    return module
