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
    assert config["schedules"]["intraday"] == "*/3 9-15,21-23 * * 1-5"
    assert config["schedules"]["healthcheck"] == "5,35 11,15,23 * * 1-5"
    assert config["healthcheck_deliver"] == "feishu:ou_29f43af572af5354dcf63c44af9ca013"

    import sys
    sys.path.insert(0, str(SKILL_DIR))
    from pvc2701_adapter import load_generator, load_publisher, load_intraday, load_healthcheck
    from pvc2701_adapter import ENABLED_JOBS, REPORT_GROUP_DELIVER, HEALTHCHECK_DELIVER

    generator = load_generator()
    publisher = load_publisher()
    intraday = load_intraday()
    healthcheck = load_healthcheck()
    assert generator.CONTRACT == "PVC2701"
    assert generator.SYMBOL == "V2701"
    assert "V2701" in generator.QUOTE_URL
    assert generator.REPORTS_DIR == SKILL_DIR / "reports"
    assert generator.RUNTIME_DIR == SKILL_DIR / "runtime" / "pvc2701_feishu_monitor"
    assert publisher.REPORTS_DIR == SKILL_DIR / "reports"
    assert set(publisher.TARGETS) == {"morning", "afternoon", "night"}
    assert intraday.CONTRACT == "PVC2701"
    assert intraday.REPORTS_DIR == SKILL_DIR / "reports"
    assert intraday.RUNTIME_DIR == SKILL_DIR / "runtime" / "pvc2701_feishu_monitor"
    assert healthcheck.GROUP_DELIVER == REPORT_GROUP_DELIVER
    assert healthcheck.ENABLED_JOBS == ENABLED_JOBS
    assert "PVC2701期货盘中关键位操作重估" in healthcheck.ENABLED_JOBS
    assert HEALTHCHECK_DELIVER.startswith("feishu:ou_")
    print("PVC2701 skill verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

