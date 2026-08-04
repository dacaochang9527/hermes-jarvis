#!/usr/bin/env python3
"""Static and lightweight runtime checks for the PVC2701 skill."""

from __future__ import annotations

import json
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    config = json.loads((SKILL_DIR / "configs" / "pvc2701_feishu.json").read_text(encoding="utf-8"))
    assert config["contract"] == "PVC2701"
    assert config["sina_symbol"] == "V2701"
    assert config["report_group"]["name"] == "pvc2701"
    assert config["report_group"]["chat_id"] == "oc_d5aa041b453e9b6f8a38fba75fa94b37"

    import sys
    sys.path.insert(0, str(SKILL_DIR))
    from pvc2701_adapter import load_generator, load_publisher

    generator = load_generator()
    publisher = load_publisher()
    assert generator.CONTRACT == "PVC2701"
    assert generator.SYMBOL == "V2701"
    assert "V2701" in generator.QUOTE_URL
    assert generator.REPORTS_DIR == SKILL_DIR / "reports"
    assert generator.RUNTIME_DIR == SKILL_DIR / "runtime" / "pvc2701_feishu_monitor"
    assert publisher.REPORTS_DIR == SKILL_DIR / "reports"
    assert set(publisher.TARGETS) == {"morning", "afternoon", "night"}
    print("PVC2701 skill verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

